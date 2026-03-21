Apoptotic Model Loading for ROS 2 Programmed cell death for machine intelligence.

Every AI model deployed on a robot gets a cryptographically verified checkpoint and a 24-hour time-to-live (TTL). At expiration, the model state is destroyed and reloaded fresh. No accumulated drift. No silent degradation.

Organization: Specialty Consultants (specialtyconsultants.co)

License: Apache-2.0

Contact: craig.mcclurkin@louisville.edu

Architecture The system follows a modular lifecycle where models are treated as ephemeral assets to ensure operational safety.

Checkpoint Registry Node: Handles SHA-256 verification and immutable storage.

Apoptotic Manager: The core 24h TTL controller that manages loading, enforcement, and reloading.

Drift Observer: Tracks KL divergence, entropy, and latency to trigger early expiration if needed.

Safe Stop Controller: Manages the velocity ramp and operator alerts during transitions.

Quick Start

Build

cd ~/ros2_ws/src git clone https://github.com/specialtyconsultants/apoptotic_loader.git cd ~/ros2_ws colcon build --packages-select apoptotic_loader

Source & Launch

source install/setup.bash

Launch full stack
ros2 launch apoptotic_loader apoptotic_stack.launch.py model_name:=welding_arm ttl_hours:=24

Monitor

Monitor TTL countdown
ros2 topic echo /apoptotic_manager/ttl_countdown

Monitor drift
ros2 topic echo /drift_observer/drift_report

Force expire (for testing)
ros2 topic pub --once /apoptotic_manager/force_expire std_msgs/String "data: 'manual'"

Nodes

Node                  Purpose                           Key Topics

checkpoint_registry   Store & verify model checkpoints ~/checkpoint_status, ~/verification_result

apoptotic_manager     Core lifecycle controller (TTL)  ~/model_status, ~/ttl_countdown, ~/lifecycle_event

drift_observer        Behavioral divergence tracking   ~/drift_report, ~/drift_alert

safe_stop_controller  Graceful degradation handler     ~/safe_stop_status, ~/operator_alert


Integration Points

The framework provides hooks for your specific model loading/destruction logic: class MyRobotManager(ApoptoticManagerNode): def _execute_model_load(self) -> bool: """Load your model here.""" self.model = torch.load('/opt/apoptotic/checkpoints/my_model.pt') return True

def execute_model_destroy(self):
    """Destroy your model state here. NO STATE CARRIES OVER."""
    del self.model
    torch.cuda.empty_cache()
    gc.collect()
Configuration See config/default.yaml for all parameters. Key settings:

ttl_seconds: 86400 (24h), 43200 (12h), 28800 (8h)

kl_threshold: 0.01 (sensitive) to 0.10 (relaxed)

stop_type: velocity_ramp | immediate_hold | return_home

early_expire_on_drift: Enable/disable drift-triggered early expiration

Why 24 Hours? Aligns with manufacturing shift cycles: Typically 8–12h shifts × 2–3.

Risk bounding: Long enough for productive operation, but short enough to bound drift risk.

Auditability: Creates natural audit boundaries for model performance.

Industry Standards: Mirrors proven SRE patterns like ephemeral containers and certificate rotation.

Contributing Apache-2.0 open source because safety standards shouldn't be proprietary. Built by Craig McClurkin / Specialty Consultants for the CyberHive CHAI AI in Manufacturing community.
