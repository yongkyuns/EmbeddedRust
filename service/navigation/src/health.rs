use crate::NavState;

/// A small standalone service that does not need its own execution context.
#[derive(Default)]
pub struct HealthService {
    observations: u64,
}

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct HealthSnapshot {
    pub observations: u64,
    pub imu_alive: bool,
    pub gnss_alive: bool,
}

impl HealthService {
    pub fn observe(&mut self, state: NavState) -> HealthSnapshot {
        self.observations = self.observations.saturating_add(1);
        HealthSnapshot {
            observations: self.observations,
            imu_alive: state.imu_sequence != 0,
            gnss_alive: state.gnss_sequence != 0,
        }
    }
}
