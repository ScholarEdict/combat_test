extends CharacterBody2D

@onready var anim := $AnimationPlayer

@export var detect_radius: float = 120.0
@export var enter_radius: float = 120.0
@export var exit_radius: float = 140.0

var speed: float = 50.0
var knockback: Vector2 = Vector2.ZERO
var knockback_timer: float = 0.0
var active_players: Dictionary = {}
var target_player_id := ""
var is_chasing_target := false


func _ready() -> void:
	get_tree().node_removed.connect(_on_tree_node_removed)
	if enter_radius <= 0.0:
		enter_radius = detect_radius
	if exit_radius < enter_radius:
		exit_radius = enter_radius
	active_players = get_active_players()
	target_player_id = select_target(active_players)


func _physics_process(delta: float) -> void:
	active_players = get_active_players()
	target_player_id = select_target(active_players)

	if knockback_timer > 0:
		position += knockback
		knockback_timer -= delta
	else:
		_movement(delta)

	move_and_slide()


func _movement(_delta: float) -> void:
	var target: CharacterBody2D = active_players.get(target_player_id)
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

	if players.has(target_player_id):
		var current_target: CharacterBody2D = players[target_player_id]
		if current_target and is_instance_valid(current_target):
			var current_distance := global_position.distance_to(current_target.global_position)
			if current_distance <= exit_radius:
				return target_player_id

	var nearest_id := ""
	var nearest_distance_sq := INF
	var chase_radius_sq := enter_radius * enter_radius
	for id in players.keys():
		var candidate: CharacterBody2D = players[id]
		if candidate == null or not is_instance_valid(candidate):
			continue

		var distance_sq := global_position.distance_squared_to(candidate.global_position)
		if distance_sq <= chase_radius_sq and distance_sq < nearest_distance_sq:
			nearest_distance_sq = distance_sq
			nearest_id = id

	return nearest_id


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
			if target_player_id == id:
				target_player_id = ""
			break
