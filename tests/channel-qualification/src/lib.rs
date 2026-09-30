//! Isolated raw-channel qualification. Not a production framework dependency.
#![forbid(unsafe_code)]

#[cfg(test)]
mod tests {
    use crossbeam_channel::{bounded, Receiver, TrySendError};
    use std::sync::{Arc, Barrier};
    use std::sync::atomic::{AtomicUsize, Ordering};
    use std::time::{Duration, Instant};

    #[derive(Debug, PartialEq, Eq)]
    struct Solution { sequence: u32, north_cm: i32 }

    #[derive(Debug, PartialEq, Eq)]
    enum Wake { Stop, Important(u32), Solution(Solution), Closed, Timeout }

    fn wait(stop: &Receiver<()>, important: &Receiver<u32>, normal: &Receiver<Solution>, timeout: Duration) -> Wake {
        crossbeam_channel::select_biased! {
            recv(stop) -> value => if value.is_ok() { Wake::Stop } else { Wake::Closed },
            recv(important) -> value => value.map(Wake::Important).unwrap_or(Wake::Closed),
            recv(normal) -> value => value.map(Wake::Solution).unwrap_or(Wake::Closed),
            default(timeout) => Wake::Timeout,
        }
    }

    #[test]
    fn dedicated_capacity_and_stop_priority() {
        let (stop, sr) = bounded(1);
        let (important, ir) = bounded(1);
        let (normal, nr) = bounded(1);
        normal.try_send(Solution { sequence: 1, north_cm: 42 }).unwrap();
        assert!(matches!(normal.try_send(Solution { sequence: 2, north_cm: 0 }), Err(TrySendError::Full(Solution { sequence: 2, .. }))));
        important.try_send(7).unwrap();
        assert_eq!(important.try_send(8), Err(TrySendError::Full(8)));
        stop.try_send(()).unwrap();
        assert_eq!(wait(&sr, &ir, &nr, Duration::ZERO), Wake::Stop);
        assert_eq!(wait(&sr, &ir, &nr, Duration::ZERO), Wake::Important(7));
        assert_eq!(wait(&sr, &ir, &nr, Duration::ZERO), Wake::Solution(Solution { sequence: 1, north_cm: 42 }));
    }

    #[test]
    fn every_source_wakes_the_same_selection() {
        for source in 0..3 {
            let (stop, sr) = bounded(1);
            let (important, ir) = bounded(1);
            let (normal, nr) = bounded(1);
            let start = Arc::new(Barrier::new(2));
            let peer = start.clone();
            let owner = std::thread::spawn(move || {
                peer.wait();
                wait(&sr, &ir, &nr, Duration::from_secs(2))
            });
            start.wait();
            match source {
                0 => stop.try_send(()).unwrap(),
                1 => important.try_send(9).unwrap(),
                _ => normal.try_send(Solution { sequence: 3, north_cm: 123 }).unwrap(),
            }
            let expected = match source {
                0 => Wake::Stop,
                1 => Wake::Important(9),
                _ => Wake::Solution(Solution { sequence: 3, north_cm: 123 }),
            };
            assert_eq!(owner.join().unwrap(), expected);
        }
    }

    #[test]
    fn empty_open_queues_timeout_without_sequential_waits() {
        let (_stop, sr) = bounded(1);
        let (_important, ir) = bounded(1);
        let (_normal, nr) = bounded(1);
        assert_eq!(wait(&sr, &ir, &nr, Duration::from_millis(5)), Wake::Timeout);
    }

    #[test]
    fn required_source_closure_is_not_ignored() {
        let (stop, sr) = bounded(1);
        let (_important, ir) = bounded(1);
        let (_normal, nr) = bounded(1);
        drop(stop);
        assert_eq!(wait(&sr, &ir, &nr, Duration::from_secs(1)), Wake::Closed);
    }

    #[test]
    fn source_failure_is_explicit_while_peer_senders_live() {
        let (_stop, sr) = bounded(1);
        let (important, ir) = bounded(1);
        let (hal, nr) = bounded(1);
        let peer = hal.clone();
        drop(hal);
        important.try_send(99).unwrap();
        assert_eq!(wait(&sr, &ir, &nr, Duration::ZERO), Wake::Important(99));
        assert_eq!(wait(&sr, &ir, &nr, Duration::from_millis(1)), Wake::Timeout);
        drop(peer);
    }

    #[test]
    fn due_deadline_checked_even_with_ready_traffic() {
        let (_stop, sr) = bounded(1);
        let (important, ir) = bounded(2);
        let (normal, nr) = bounded(2);
        important.try_send(1).unwrap();
        normal.try_send(Solution { sequence: 1, north_cm: 0 }).unwrap();
        let due = Instant::now();
        let mut ticks = 0;
        if Instant::now() >= due { ticks += 1; }
        assert_eq!(wait(&sr, &ir, &nr, Duration::ZERO), Wake::Important(1));
        assert_eq!(ticks, 1);
        assert_eq!(wait(&sr, &ir, &nr, Duration::ZERO), Wake::Solution(Solution { sequence: 1, north_cm: 0 }));
    }

    #[test]
    fn synthetic_provider_cancels_without_draining_full_queue() {
        let (normal, _nr) = bounded(1);
        normal.try_send(Solution { sequence: 0, north_cm: 0 }).unwrap();
        let (cancel, cancellation) = bounded(1);
        let (started, start) = bounded(1);
        let (finished, finish) = bounded(1);
        let provider = std::thread::spawn(move || {
            assert!(matches!(normal.try_send(Solution { sequence: 1, north_cm: 0 }), Err(TrySendError::Full(_))));
            started.try_send(()).unwrap();
            cancellation.recv_timeout(Duration::from_secs(2)).unwrap();
            // This models quiescence, not a real UART cancellation implementation.
            drop(normal);
            finished.try_send(()).unwrap();
        });
        start.recv_timeout(Duration::from_secs(2)).unwrap();
        cancel.try_send(()).unwrap();
        finish.recv_timeout(Duration::from_secs(2)).unwrap();
        provider.join().unwrap();
    }

    #[test]
    fn rejected_owned_payload_and_queued_drop_are_reclaimed() {
        #[derive(Debug)]
        struct Tracked { id: u8, drops: Arc<AtomicUsize> }
        impl Drop for Tracked {
            fn drop(&mut self) { self.drops.fetch_add(1, Ordering::SeqCst); }
        }
        let drops = Arc::new(AtomicUsize::new(0));
        let (tx, rx) = bounded(1);
        tx.try_send(Tracked { id: 1, drops: drops.clone() }).unwrap();
        let rejected = tx.try_send(Tracked { id: 2, drops: drops.clone() }).unwrap_err();
        assert_eq!(drops.load(Ordering::SeqCst), 0);
        match rejected { TrySendError::Full(value) => { assert_eq!(value.id, 2); drop(value); }, _ => panic!("wrong rejection") }
        drop(rx);
        assert_eq!(drops.load(Ordering::SeqCst), 2);
        let rejected = tx.try_send(Tracked { id: 3, drops: drops.clone() }).unwrap_err();
        assert!(matches!(rejected, TrySendError::Disconnected(_)));
        drop(rejected);
        assert_eq!(drops.load(Ordering::SeqCst), 3);
    }
}
