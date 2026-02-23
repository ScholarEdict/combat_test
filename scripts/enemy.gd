extends CharacterBody2D

@onready var anim := $AnimationPlayer

@export var detect_radius: float = 120.0
@export var enter_radius: float = 120.0
@export var exit_radius: float = 140.0

var speed: float = 50.0
var knockback: Vector2 = Vector2.ZERO
var knockback_timer: float = 0.0
var active_players: Dictionary = {}
var current_target_id := ""
var aggro_order: Dictionary = {}
var players_in_range: Dictionary = {}
var is_chasing_target := false


func _ready() -> void:
	get_tree().node_removed.connect(_on_tree_node_removed)
	if enter_radius <= 0.0:
		enter_radius = detect_radius
	if exit_radius < enter_radius:
		exit_radius = enter_radius
	active_players = get_active_players()
	_update_players_in_range(active_players)
	current_target_id = select_target(players_in_range)


func _physics_process(delta: float) -> void:
	active_players = get_active_players()
	_update_players_in_range(active_players)
	current_target_id = select_target(players_in_range)

	if knockback_timer > 0:
		position += knockback
		knockback_timer -= delta
	else:
		_movement(delta)

	move_and_slide()


func _movement(_delta: float) -> void:
	var target: CharacterBody2D = active_players.get(current_target_id)
	if target == null:
		velocity = Vector2.ZERO
		is_chasing_target = false
		_play_idle_if_available()
		return

	var distance_to_target := global_position.distance_to(target.global_position)
	var chase_radius := exit_radius if is_chasing_target else enter_radius
	if distance_to_target > chase_radius:
		velocity = Vector2.ZERO
		is_chasing_target = false
		_play_idle_if_available()
		return

	var direction := (target.global_position - global_position).normalized()
	velocity = direction * speed
	is_chasing_target = true


func _process(_delta: float) -> void:
	pass


func play_anim() -> void:
	anim.play("got_attack")


func apply_knockback(direction: Vector2, force: float, knockback_dur: float) -> void:
	knockback = direction * force
	knockback_timer = knockback_dur


func get_active_players() -> Dictionary:
	var players_by_id: Dictionary = {}
	for node in get_tree().get_nodes_in_group("player"):
		if not (node is CharacterBody2D):
			continue
		if not is_instance_valid(node) or not node.is_inside_tree():
			continue

		var id := str(node.get("player_id"))
		if id.is_empty():
			id = str(node.get_instance_id())

		players_by_id[id] = node

	return players_by_id


func select_target(players: Dictionary) -> String:
	if players.is_empty():
		is_chasing_target = false
		return ""

	if players.has(current_target_id):
		var current_target: CharacterBody2D = players[current_target_id]
		if current_target and is_instance_valid(current_target):
			var current_distance := global_position.distance_to(current_target.global_position)
			if current_distance <= exit_radius:
				return current_target_id

	var sorted_ids := players.keys()
	sorted_ids.sort_custom(_compare_aggro_priority)
	return str(sorted_ids.front()) if not sorted_ids.is_empty() else ""


func _update_players_in_range(players: Dictionary) -> void:
	var updated_in_range: Dictionary = {}
	for id in players.keys():
		var player: CharacterBody2D = players[id]
		if player == null or not is_instance_valid(player):
			continue

		var is_already_tracking := players_in_range.has(id)
		var radius := exit_radius if is_already_tracking else enter_radius
		if global_position.distance_to(player.global_position) > radius:
			continue

		updated_in_range[id] = player
		if not aggro_order.has(id):
			aggro_order[id] = {
				"entered_at_ms": Time.get_ticks_msec(),
				"player_id": str(id),
			}

	players_in_range = updated_in_range

	for id in aggro_order.keys():
		if not players_in_range.has(id):
			aggro_order.erase(id)


func _compare_aggro_priority(left_id: Variant, right_id: Variant) -> bool:
	var left_key := str(left_id)
	var right_key := str(right_id)
	var left_entry: Dictionary = aggro_order.get(left_key, {})
	var right_entry: Dictionary = aggro_order.get(right_key, {})

	var left_time := int(left_entry.get("entered_at_ms", 0))
	var right_time := int(right_entry.get("entered_at_ms", 0))
	if left_time == right_time:
		return left_key < right_key

	return left_time < right_time


func _play_idle_if_available() -> void:
	if anim == null:
		return
	if anim.has_animation("idle"):
		anim.play("idle")


func _on_tree_node_removed(node: Node) -> void:
	if not (node is CharacterBody2D):
		return
	if not node.is_in_group("player"):
		return

	for id in active_players.keys():
		if active_players[id] == node:
			active_players.erase(id)
			players_in_range.erase(id)
			aggro_order.erase(id)
			if current_target_id == id:
				current_target_id = ""
			break
