fn main() {
    for scenario in nxrs_simulator::scenarios::SCENARIOS {
        (scenario.run)();
        println!("PASS {}", scenario.name);
    }
    nxrs_simulator::threaded::exercise_owner_thread();
    println!("PASS bounded native owner thread and joined shutdown");
    println!("{} shared scenarios passed", nxrs_simulator::scenarios::SCENARIOS.len());
}
