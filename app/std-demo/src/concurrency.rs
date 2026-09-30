use super::DemoResult;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::mpsc::{self, RecvTimeoutError, TrySendError};
use std::sync::{Arc, Condvar, Mutex, OnceLock};
use std::thread;
use std::time::{Duration, Instant};

pub(super) fn ownership() -> DemoResult {
    let config = Arc::new(OnceLock::new());
    config
        .set((100u32, "imu"))
        .map_err(|_| "config already initialized")?;
    let owner = config.clone(); // Shares immutable configuration, not actor state.
    let join = thread::Builder::new()
        .name("std-owner".into())
        .stack_size(32768)
        .spawn(move || *owner.get().unwrap())?;
    assert_eq!(join.join().map_err(|_| "owner panicked")?, (100, "imu"));
    assert_eq!(Arc::strong_count(&config), 1);
    let boxed: Box<[u16]> = vec![1, 2, 3].into_boxed_slice();
    assert_eq!(boxed.iter().sum::<u16>(), 6);
    println!("  Box owns; Arc shares immutable config; OnceLock publishes once; thread joined");
    Ok(())
}

pub(super) fn channels() -> DemoResult {
    let (sender, receiver) = mpsc::sync_channel(1);
    sender.try_send(7u8)?;
    assert!(matches!(sender.try_send(8), Err(TrySendError::Full(8))));
    assert_eq!(receiver.recv()?, 7);
    drop(receiver);
    assert!(matches!(
        sender.try_send(9),
        Err(TrySendError::Disconnected(9))
    ));

    // Move a preallocated buffer through a zero-slot rendezvous and back.
    // No clone of its contents and no per-request reply-channel creation.
    let (request, inbox) = mpsc::sync_channel::<Vec<u8>>(0);
    let (reply, replies) = mpsc::sync_channel(1);
    let worker = thread::Builder::new()
        .name("std-channel".into())
        .stack_size(32768)
        .spawn(move || {
            if let Ok(mut buffer) = inbox.recv() {
                buffer[0] = 42;
                let _ = reply.send(buffer);
            }
        })?;
    let mut buffer = Vec::with_capacity(16);
    buffer.push(1);
    let capacity = buffer.capacity();
    request.send(buffer)?;
    let answer = replies.recv_timeout(Duration::from_secs(2));
    drop(request);
    worker.join().map_err(|_| "channel worker panicked")?;
    let answer = answer?;
    assert_eq!(answer[0], 42);
    assert_eq!(answer.capacity(), capacity);
    println!("  sync_channel: full/disconnected preserve ownership; capacity=0 rendezvous; buffer moved back");
    println!("  mpsc::channel is unbounded: intentionally NOT used for an embedded work backlog");
    Ok(())
}

pub(super) fn synchronization() -> DemoResult {
    let state = Arc::new((Mutex::new(false), Condvar::new()));
    let other = state.clone();
    let published = Arc::new(AtomicBool::new(false));
    let flag = published.clone();
    let worker = thread::Builder::new()
        .name("std-predicate".into())
        .stack_size(32768)
        .spawn(move || {
            let (lock, changed) = &*other;
            let guard = lock.lock().unwrap();
            // Always re-check a predicate; notifications can be spurious.
            let guard = changed.wait_while(guard, |ready| !*ready).unwrap();
            assert!(*guard);
            flag.store(true, Ordering::Release);
        })?;
    let (lock, changed) = &*state;
    *lock.lock().map_err(|_| "poisoned ready mutex")? = true;
    changed.notify_one();
    worker.join().map_err(|_| "predicate worker panicked")?;
    assert!(published.load(Ordering::Acquire));
    println!(
        "  Mutex + Condvar: predicate wait; AtomicBool: release/acquire; no AtomicU64 requirement"
    );
    Ok(())
}

pub(super) fn deadlines() -> DemoResult {
    // A timeout comes from an absolute deadline, not repeated full-duration
    // waits that silently extend the caller's budget after unrelated events.
    let (sender, receiver) = mpsc::sync_channel::<u8>(1);
    sender.send(1)?;
    let deadline = Instant::now() + Duration::from_millis(2);
    assert_eq!(
        receiver.recv_timeout(deadline.saturating_duration_since(Instant::now()))?,
        1
    );
    assert_eq!(
        receiver.recv_timeout(deadline.saturating_duration_since(Instant::now())),
        Err(RecvTimeoutError::Timeout)
    );
    drop(sender);
    assert_eq!(receiver.recv(), Err(mpsc::RecvError));
    println!("  Instant + Duration: absolute budget, timeout, then clean disconnect");
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn ownership_recipe() {
        ownership().unwrap();
    }
    #[test]
    fn channel_recipe() {
        channels().unwrap();
    }
    #[test]
    fn predicate_recipe() {
        synchronization().unwrap();
    }
    #[test]
    fn deadline_recipe() {
        deadlines().unwrap();
    }
}
