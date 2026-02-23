extends CharacterBody2D

@export var speed := 100.0
@export var is_local_player := true
@export var player_id := ""

var last_dir := Vector2.DOWN
var radius := 15.0
var input_dto := PlayerSimulation.make_input(Vector2.ZERO, Vector2.DOWN, false)

@onready var anim: AnimatedSprite2D = $AnimatedSprite2D
@onready var sanim: AnimationPlayer = $sword/AnimationPlayer

func _ready() -> void:
	add_to_group("player")


func _physics_process(_delta: float) -> void:
	if not is_local_player:
		return

	input_dto = _collect_local_input()
	_run_simulation(input_dto)
	move_and_slide()


func _run_simulation(dto: Dictionary) -> void:
	var state := {
		"last_dir": last_dir,
	}
	var result := PlayerSimulation.step(state, dto, speed, radius)
	velocity = result["velocity"]
	last_dir = result["last_dir"]

	$sword.position = result["sword_position"]
	$sword.rotation = result["sword_rotation"]
	anim.flip_h = result["flip_h"]

	var animation_name: String = result["animation_name"]
	if anim.animation != animation_name:
		anim.play(animation_name)

	if result["attack_pressed"]:
		sanim.play("swing")


func _collect_local_input() -> Dictionary:
	var move_vector := Input.get_vector("A", "D", "W", "S")
	var aim_vector := get_global_mouse_position() - global_position
	if aim_vector.length_squared() > 0.0001:
		aim_vector = aim_vector.normalized()
	return PlayerSimulation.make_input(
		move_vector,
		aim_vector,
		Input.is_action_just_pressed("click")
	)


func set_input_dto(dto: Dictionary) -> void:
	input_dto = dto


func get_net_state() -> Dictionary:
	return {
		"position": {"x": global_position.x, "y": global_position.y},
		"velocity": {"x": velocity.x, "y": velocity.y},
		"last_dir": {"x": last_dir.x, "y": last_dir.y},
		"attack_pressed": bool(input_dto.get("attack_pressed", false)),
	}


func apply_snapshot(snapshot: Dictionary) -> void:
	if snapshot.has("position"):
		global_position = _to_vector2(snapshot["position"])
	if snapshot.has("velocity"):
		velocity = _to_vector2(snapshot["velocity"])
	if snapshot.has("last_dir"):
		last_dir = _to_vector2(snapshot["last_dir"]).normalized()
	elif snapshot.has("aim"):
		last_dir = _to_vector2(snapshot["aim"]).normalized()

	$sword.position = _to_vector2(snapshot.get("sword_position", last_dir * radius))
	$sword.rotation = float(snapshot.get("sword_rotation", last_dir.angle()))
	anim.flip_h = bool(snapshot.get("flip_h", last_dir.x < 0))

	if snapshot.has("animation"):
		var animation_name: String = snapshot["animation"]
		if anim.animation != animation_name:
			anim.play(animation_name)
	elif velocity.length_squared() > 0.0001:
		if anim.animation != "walk":
			anim.play("walk")
	else:
		if anim.animation != "idle":
			anim.play("idle")

	if snapshot.get("attack_pressed", false) or snapshot.get("is_attacking", false):
		sanim.play("swing")


func play_anim() -> void:
	if sanim:
		sanim.play("swing")


func apply_knockback(direction: Vector2, force: float, _knockback_dur: float) -> void:
	global_position += direction * force


func _to_vector2(raw_value: Variant) -> Vector2:
	if raw_value is Vector2:
		return raw_value
	if raw_value is Array and raw_value.size() >= 2:
		return Vector2(float(raw_value[0]), float(raw_value[1]))
	if raw_value is Dictionary:
		return Vector2(float(raw_value.get("x", 0.0)), float(raw_value.get("y", 0.0)))
	return Vector2.ZERO


func spawn_enemy() -> void:
	var enemy = preload("res://scenes/enemies.tscn").instantiate()
	get_parent().add_child(enemy)
