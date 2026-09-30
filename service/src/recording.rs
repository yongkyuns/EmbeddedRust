use nxrs_storage_api::{Frame, Storage};
use crate::{Error, SinkStats};

pub trait Recordings {
    fn record(&mut self, frame: Frame<'_>) -> Result<(), Error>;
    fn flush(&mut self) -> Result<(), Error>;
}

pub struct RecordingService<D> {
    device: D,
    stats: SinkStats,
}

impl<D: Storage> RecordingService<D> {
    pub fn new(device: D) -> Self { Self { device, stats: SinkStats::default() } }
    pub fn stats(&self) -> SinkStats { self.stats }
    pub fn backend(&self) -> &D { &self.device }
}

impl<D: Storage> Recordings for RecordingService<D> {
    fn record(&mut self, frame: Frame<'_>) -> Result<(), Error> {
        match self.device.append(frame) {
            Ok(()) => {
                self.stats.accepted = self.stats.accepted.saturating_add(1);
                Ok(())
            }
            Err(error) => {
                self.stats.errors = self.stats.errors.saturating_add(1);
                Err(error.into())
            }
        }
    }

    fn flush(&mut self) -> Result<(), Error> { self.device.flush().map_err(Into::into) }
}
