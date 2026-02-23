extends Node2D

@export var player_scene: PackedScene
@export var enemy_scene: PackedScene

var players: Dictionary = {}
var entities: Dictionary = {}

func _ready() -> void:
	if player_scene == null:
		player_scene = preload("res://scenes/player.tscn")
	if enemy_scene == null:
		enemy_scene = preload("res://scenes/enemies.tscn")

	spawn_from_state({
		"players": [
			{
				"id": "local",
				"position": Vector2(196, 143),
				"is_local": true,
			}
		],
		"entities": [
			{
				"id": "enemy_1",
				"type": "enemy",
				"position": Vector2(221, 156),
			}
		]
	})


func spawn_from_state(payload: Dictionary) -> void:
	for player_payload in payload.get("players", []):
		_spawn_or_update_player(player_payload)

	for entity_payload in payload.get("entities", []):
		_spawn_or_update_entity(entity_payload)


func apply_snapshot(snapshot: Dictionary) -> void:
	for player_snapshot in snapshot.get("players", []):
		var player = _spawn_or_update_player(player_snapshot)
		if player:
			player.apply_snapshot(player_snapshot)

	for entity_snapshot in snapshot.get("entities", []):
		_spawn_or_update_entity(entity_snapshot)


func _spawn_or_update_player(player_payload: Dictionary) -> CharacterBody2D:
	var id := str(player_payload.get("id", ""))
	if id.is_empty():
		return null

	var player: CharacterBody2D = players.get(id)
	if player == null:
		player = player_scene.instantiate()
		player.player_id = id
		add_child(player)
		players[id] = player

	if player_payload.has("is_local"):
		player.is_local_player = bool(player_payload["is_local"])
	if player_payload.has("position"):
		player.global_position = _to_vector2(player_payload["position"])

	if player.is_local_player and player.get_node_or_null("Camera2D") == null:
		var camera := Camera2D.new()
		camera.zoom = Vector2(5, 5)
		camera.make_current()
		player.add_child(camera)

	return player


func _spawn_or_update_entity(entity_payload: Dictionary) -> Node2D:
	var entity_id := str(entity_payload.get("id", ""))
	if entity_id.is_empty():
		return null

	var entity: Node2D = entities.get(entity_id)
	if entity == null:
		var entity_type := str(entity_payload.get("type", ""))
		if entity_type != "enemy":
			return null
		entity = enemy_scene.instantiate()
		entity.name = entity_id
		add_child(entity)
		entities[entity_id] = entity

	if entity_payload.has("position"):
		entity.global_position = _to_vector2(entity_payload["position"])

	if entity_payload.has("rotation"):
		entity.rotation = float(entity_payload["rotation"])

	return entity


func _to_vector2(raw_value: Variant) -> Vector2:
	if raw_value is Vector2:
		return raw_value
	if raw_value is Array and raw_value.size() >= 2:
		return Vector2(float(raw_value[0]), float(raw_value[1]))
	if raw_value is Dictionary:
		return Vector2(float(raw_value.get("x", 0.0)), float(raw_value.get("y", 0.0)))
	return Vector2.ZERO
