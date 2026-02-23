class_name PlayerSimulation
extends RefCounted

static func make_input(move_vector: Vector2, aim_vector: Vector2, attack_pressed: bool) -> Dictionary:
	return {
		"move_vector": move_vector,
		"aim_vector": aim_vector,
		"attack_pressed": attack_pressed,
	}


static func step(state: Dictionary, input_dto: Dictionary, speed: float, radius: float) -> Dictionary:
	var move_vector: Vector2 = input_dto.get("move_vector", Vector2.ZERO)
	var aim_vector: Vector2 = input_dto.get("aim_vector", Vector2.ZERO)
	var attack_pressed: bool = input_dto.get("attack_pressed", false)
	var velocity := move_vector * speed
	var last_dir: Vector2 = state.get("last_dir", Vector2.DOWN)

	if aim_vector.length_squared() > 0.0001:
		last_dir = aim_vector.normalized()
	elif velocity.length_squared() > 0.0001:
		last_dir = velocity.normalized()

	var animation_name := "idle"
	if velocity.length_squared() > 0.0001:
		animation_name = "walk"

	return {
		"velocity": velocity,
		"last_dir": last_dir,
		"sword_position": last_dir * radius,
		"sword_rotation": last_dir.angle(),
		"animation_name": animation_name,
		"flip_h": last_dir.x < 0,
		"attack_pressed": attack_pressed,
	}
