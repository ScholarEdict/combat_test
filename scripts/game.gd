extends Node2D

@export var player_scene: PackedScene
@export var enemy_scene: PackedScene

var players: Dictionary = {}
var entities: Dictionary = {}
var api_client: ApiClient

var auth_layer: CanvasLayer
var status_label: Label
var credential_input: LineEdit
var password_input: LineEdit
var username_input: LineEdit
var email_input: LineEdit

func _ready() -> void:
	if player_scene == null:
		player_scene = preload("res://scenes/player.tscn")
	if enemy_scene == null:
		enemy_scene = preload("res://scenes/enemies.tscn")

	api_client = ApiClient.new()
	add_child(api_client)

	await _gate_auth_then_start_game()


func _gate_auth_then_start_game() -> void:
	if api_client.has_session():
		_set_status("Found session, loading profile...")
		var profile_result := await api_client.fetch_profile()
		if profile_result.get("ok", false):
			_start_gameplay(profile_result["data"])
			return
		api_client.clear_session()

	_show_auth_ui()


func _start_gameplay(data: Dictionary) -> void:
	if auth_layer:
		auth_layer.queue_free()
		auth_layer = null

	print("Authenticated user: ", data.get("profile", {}))
	print("Loaded assets: ", data.get("assets", {}))

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


func _show_auth_ui() -> void:
	auth_layer = CanvasLayer.new()
	add_child(auth_layer)

	var root := Control.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	auth_layer.add_child(root)

	var panel := PanelContainer.new()
	panel.custom_minimum_size = Vector2(320, 260)
	panel.position = Vector2(40, 40)
	root.add_child(panel)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 8)
	panel.add_child(vbox)

	var title := Label.new()
	title.text = "Login or Register"
	vbox.add_child(title)

	credential_input = LineEdit.new()
	credential_input.placeholder_text = "username or email"
	vbox.add_child(credential_input)

	password_input = LineEdit.new()
	password_input.placeholder_text = "password"
	password_input.secret = true
	vbox.add_child(password_input)

	username_input = LineEdit.new()
	username_input.placeholder_text = "new username"
	vbox.add_child(username_input)

	email_input = LineEdit.new()
	email_input.placeholder_text = "new email"
	vbox.add_child(email_input)

	var buttons := HBoxContainer.new()
	vbox.add_child(buttons)

	var login_button := Button.new()
	login_button.text = "Login"
	login_button.pressed.connect(_on_login_pressed)
	buttons.add_child(login_button)

	var register_button := Button.new()
	register_button.text = "Register"
	register_button.pressed.connect(_on_register_pressed)
	buttons.add_child(register_button)

	status_label = Label.new()
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status_label.text = "Please authenticate to continue"
	vbox.add_child(status_label)


func _on_login_pressed() -> void:
	_set_status("Logging in...")
	var login_result := await api_client.login_user(credential_input.text, password_input.text)
	if not login_result.get("ok", false):
		_show_error(login_result)
		return

	_set_status("Login success. Loading profile...")
	var profile_result := await api_client.fetch_profile()
	if not profile_result.get("ok", false):
		_show_error(profile_result)
		return

	_start_gameplay(profile_result["data"])


func _on_register_pressed() -> void:
	_set_status("Registering...")
	var register_result := await api_client.register_user(username_input.text, email_input.text, password_input.text)
	if not register_result.get("ok", false):
		_show_error(register_result)
		return

	_set_status("Registration success. Loading profile...")
	var profile_result := await api_client.fetch_profile()
	if not profile_result.get("ok", false):
		_show_error(profile_result)
		return

	_start_gameplay(profile_result["data"])


func _show_error(result: Dictionary) -> void:
	var error_data: Dictionary = result.get("error", {})
	_set_status("%s: %s" % [error_data.get("code", "UNKNOWN_ERROR"), error_data.get("message", "Request failed")])


func _set_status(message: String) -> void:
	if status_label:
		status_label.text = message


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
