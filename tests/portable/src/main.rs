fn main() {
    for scenario in rustcam_simulator::scenarios::SCENARIOS {
        (scenario.run)();
        println!("PASS {}", scenario.name);
    }
    rustcam_simulator::threaded::exercise_owner_thread();
    println!("PASS bounded native owner thread and joined shutdown");
    println!("{} shared scenarios passed", rustcam_simulator::scenarios::SCENARIOS.len());
}
