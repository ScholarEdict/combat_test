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

const AUTH_MODE_LOGIN := "login"
const AUTH_MODE_REGISTER := "register"
var auth_mode := AUTH_MODE_LOGIN

var lobby_layer: CanvasLayer
var lobby_status_label: Label
var profile_name_input: LineEdit
var profile_select: OptionButton
var profile_map: Dictionary = {}
var profile_ids: Array[String] = []
var selected_profile_id := ""
var current_account: Dictionary = {}

var gameplay_ui_layer: CanvasLayer
var account_label: Label
var online_label: Label
var coordinate_monitor_label: Label
var back_to_lobby_button: Button
var presence_poll_timer: Timer
var world_poll_timer: Timer
var position_sync_timer: Timer

var _last_synced_position := Vector2.ZERO
var _spawn_position := Vector2.ZERO
var _position_sync_in_flight := false

func _ready() -> void:
	if player_scene == null:
		player_scene = preload("res://scenes/player.tscn")
	if enemy_scene == null:
		enemy_scene = preload("res://scenes/enemies.tscn")

	api_client = ApiClient.new()
	add_child(api_client)
	api_client.presence_changed.connect(_on_presence_changed)

	await _gate_auth_then_start_game()


func _notification(what: int) -> void:
	if what == NOTIFICATION_WM_CLOSE_REQUEST:
		_disconnect_presence_no_wait()


func _process(_delta: float) -> void:
	_update_coordinate_monitor()


func _disconnect_presence_no_wait() -> void:
	if api_client and api_client.has_session() and not selected_profile_id.is_empty():
		api_client.disconnect_session(selected_profile_id)


func _gate_auth_then_start_game() -> void:
	if api_client.has_session():
		var profile_result := await api_client.fetch_profile()
		if profile_result.get("ok", false):
			await _show_lobby(profile_result["data"].get("profile", {}))
			return
		api_client.clear_session()

	_show_auth_ui()


func _show_auth_ui(mode: String = AUTH_MODE_LOGIN, status_message: String = "") -> void:
	auth_mode = mode

	if lobby_layer:
		lobby_layer.queue_free()
		lobby_layer = null
	if auth_layer:
		auth_layer.queue_free()
		auth_layer = null

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
	title.text = "Login" if auth_mode == AUTH_MODE_LOGIN else "Register"
	vbox.add_child(title)

	credential_input = null
	username_input = null
	email_input = null
	password_input = LineEdit.new()

	if auth_mode == AUTH_MODE_LOGIN:
		credential_input = LineEdit.new()
		credential_input.placeholder_text = "username or email"
		vbox.add_child(credential_input)
	else:
		username_input = LineEdit.new()
		username_input.placeholder_text = "new username"
		vbox.add_child(username_input)

		email_input = LineEdit.new()
		email_input.placeholder_text = "new email"
		vbox.add_child(email_input)

	password_input.placeholder_text = "password"
	password_input.secret = true
	vbox.add_child(password_input)

	var buttons := HBoxContainer.new()
	vbox.add_child(buttons)

	if auth_mode == AUTH_MODE_LOGIN:
		var login_button := Button.new()
		login_button.text = "Login"
		login_button.pressed.connect(_on_login_pressed)
		buttons.add_child(login_button)

		var register_button := Button.new()
		register_button.text = "Register"
		register_button.pressed.connect(_on_switch_to_register_pressed)
		buttons.add_child(register_button)
	else:
		var create_account_button := Button.new()
		create_account_button.text = "Create Account"
		create_account_button.pressed.connect(_on_register_pressed)
		buttons.add_child(create_account_button)

		var back_to_login_button := Button.new()
		back_to_login_button.text = "Back to Login"
		back_to_login_button.pressed.connect(_on_switch_to_login_pressed)
		buttons.add_child(back_to_login_button)

	status_label = Label.new()
	status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	status_label.text = status_message if not status_message.is_empty() else "Please authenticate to continue"
	vbox.add_child(status_label)


func _show_lobby(account_profile: Dictionary) -> void:
	current_account = account_profile
	if auth_layer:
		auth_layer.queue_free()
		auth_layer = null
	if gameplay_ui_layer:
		gameplay_ui_layer.queue_free()
		gameplay_ui_layer = null

	_clear_world()

	if lobby_layer == null:
		lobby_layer = CanvasLayer.new()
		add_child(lobby_layer)
		var root := Control.new()
		root.set_anchors_preset(Control.PRESET_FULL_RECT)
		lobby_layer.add_child(root)

		var panel := PanelContainer.new()
		panel.custom_minimum_size = Vector2(430, 240)
		panel.position = Vector2(40, 40)
		root.add_child(panel)

		var vbox := VBoxContainer.new()
		vbox.add_theme_constant_override("separation", 8)
		panel.add_child(vbox)

		var title := Label.new()
		title.text = "Create/Select profile then click Play"
		vbox.add_child(title)

		var account_label_local := Label.new()
		account_label_local.text = "Logged in as: %s" % str(account_profile.get("username", "unknown"))
		vbox.add_child(account_label_local)

		var create_row := HBoxContainer.new()
		vbox.add_child(create_row)

		profile_name_input = LineEdit.new()
		profile_name_input.placeholder_text = "new profile display name"
		profile_name_input.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		create_row.add_child(profile_name_input)

		var create_button := Button.new()
		create_button.text = "Create Profile"
		create_button.pressed.connect(_on_create_profile_pressed)
		create_row.add_child(create_button)

		profile_select = OptionButton.new()
		profile_select.item_selected.connect(_on_profile_selected)
		vbox.add_child(profile_select)

		var action_row := HBoxContainer.new()
		vbox.add_child(action_row)

		var play_button := Button.new()
		play_button.text = "Play"
		play_button.pressed.connect(_on_play_pressed)
		action_row.add_child(play_button)

		var logout_button := Button.new()
		logout_button.text = "Logout"
		logout_button.pressed.connect(_on_logout_pressed)
		action_row.add_child(logout_button)

		lobby_status_label = Label.new()
		lobby_status_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
		lobby_status_label.text = "Create or select a profile to continue."
		vbox.add_child(lobby_status_label)

	await _refresh_profile_list()


func _refresh_profile_list() -> void:
	if profile_select == null:
		return

	profile_select.clear()
	profile_map.clear()
	profile_ids.clear()
	selected_profile_id = ""

	var list_result := await api_client.list_profiles()
	if not list_result.get("ok", false):
		_show_lobby_error(list_result)
		return

	var profiles: Array = list_result["data"].get("profiles", [])
	for entry in profiles:
		if entry is Dictionary:
			var profile_entry: Dictionary = entry
			var player_id := str(profile_entry.get("player_id", ""))
			var label := str(profile_entry.get("display_name", "Unnamed"))
			if not player_id.is_empty():
				profile_select.add_item("%s (%s)" % [label, player_id.substr(0, 6)])
				profile_map[player_id] = profile_entry
				profile_ids.append(player_id)

	if profile_select.item_count > 0:
		profile_select.selected = 0
		selected_profile_id = profile_ids[0]
		lobby_status_label.text = "Profile selected. Click Play to start the game."
	else:
		lobby_status_label.text = "No profiles yet. Create one, then click Play."


func _on_profile_selected(index: int) -> void:
	if index < 0 or index >= profile_ids.size():
		selected_profile_id = ""
		return
	selected_profile_id = profile_ids[index]
	lobby_status_label.text = "Profile selected. Click Play to start the game."


func _on_create_profile_pressed() -> void:
	var display_name := profile_name_input.text.strip_edges()
	if display_name.is_empty():
		lobby_status_label.text = "Display name is required"
		return

	var create_result := await api_client.create_profile(display_name)
	if not create_result.get("ok", false):
		_show_lobby_error(create_result)
		return

	profile_name_input.text = ""
	lobby_status_label.text = "Profile created."
	await _refresh_profile_list()


func _on_play_pressed() -> void:
	if selected_profile_id.is_empty():
		lobby_status_label.text = "Select or create a profile first"
		return

	var selected_profile: Dictionary = profile_map.get(selected_profile_id, {})
	if selected_profile.is_empty():
		lobby_status_label.text = "Selected profile not found"
		return

	selected_profile_id = str(selected_profile.get("player_id", ""))
	await _start_gameplay(selected_profile)


func _start_gameplay(selected_profile: Dictionary) -> void:
	if lobby_layer:
		lobby_layer.queue_free()
		lobby_layer = null

	_ensure_gameplay_ui()
	account_label.text = "Connected as %s / %s" % [
		str(current_account.get("username", "unknown")),
		str(selected_profile.get("display_name", "profile")),
	]

	var player_id := str(selected_profile.get("player_id", ""))
	if player_id.is_empty():
		_show_lobby_error({
			"error": {
				"code": "MISSING_PLAYER_ID",
				"message": "Selected profile is missing player_id",
			}
		})
		await _show_lobby(current_account)
		return

	var connect_result := await api_client.connect_session(player_id)
	if not connect_result.get("ok", false):
		_show_error(connect_result)
		await _show_lobby(current_account)
		return

	await api_client.fetch_online_users()
	await _refresh_world_state(selected_profile)

	if presence_poll_timer:
		presence_poll_timer.start()
	if world_poll_timer:
		world_poll_timer.start()
	if position_sync_timer:
		position_sync_timer.start()

	_last_synced_position = Vector2(
		float(selected_profile.get("position", {}).get("x", 0.0)),
		float(selected_profile.get("position", {}).get("y", 0.0))
	)
	_spawn_position = _last_synced_position
	_update_coordinate_monitor()


func _refresh_world_state(selected_profile: Dictionary) -> void:
	var world_result := await api_client.fetch_world_state()
	if not world_result.get("ok", false):
		_show_error(world_result)
		return

	var players_payload: Array = []
	for entry in world_result["data"].get("players", []):
		if entry is Dictionary:
			var item: Dictionary = entry
			players_payload.append({
				"id": str(item.get("player_id", "")),
				"position": item.get("position", {"x": 0.0, "y": 0.0}),
				"is_local": str(item.get("player_id", "")) == str(selected_profile.get("player_id", "")),
			})

	_apply_world_state({
		"players": players_payload,
		"entities": [],
	})


func _apply_world_state(payload: Dictionary) -> void:
	var seen_player_ids: Dictionary = {}
	for player_payload in payload.get("players", []):
		var id := str(player_payload.get("id", ""))
		if id.is_empty():
			continue
		seen_player_ids[id] = true
		_spawn_or_update_player(player_payload)

	for id in players.keys():
		if seen_player_ids.has(id):
			continue
		var stale_player: CharacterBody2D = players.get(id)
		if is_instance_valid(stale_player):
			stale_player.queue_free()
		players.erase(id)

	var seen_entity_ids: Dictionary = {}
	for entity_payload in payload.get("entities", []):
		var entity_id := str(entity_payload.get("id", ""))
		if entity_id.is_empty():
			continue
		seen_entity_ids[entity_id] = true
		_spawn_or_update_entity(entity_payload)

	for entity_id in entities.keys():
		if seen_entity_ids.has(entity_id):
			continue
		var stale_entity: Node2D = entities.get(entity_id)
		if is_instance_valid(stale_entity):
			stale_entity.queue_free()
		entities.erase(entity_id)


func _ensure_gameplay_ui() -> void:
	if gameplay_ui_layer:
		return

	gameplay_ui_layer = CanvasLayer.new()
	add_child(gameplay_ui_layer)

	var root := Control.new()
	root.set_anchors_preset(Control.PRESET_FULL_RECT)
	gameplay_ui_layer.add_child(root)

	var panel := PanelContainer.new()
	panel.position = Vector2(12, 12)
	panel.custom_minimum_size = Vector2(320, 110)
	root.add_child(panel)

	var vbox := VBoxContainer.new()
	vbox.add_theme_constant_override("separation", 6)
	panel.add_child(vbox)

	account_label = Label.new()
	account_label.text = "Connected as: -"
	vbox.add_child(account_label)

	online_label = Label.new()
	online_label.text = "Online players: -"
	vbox.add_child(online_label)

	coordinate_monitor_label = Label.new()
	coordinate_monitor_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	coordinate_monitor_label.text = "Position monitor: waiting for local player"
	vbox.add_child(coordinate_monitor_label)

	back_to_lobby_button = Button.new()
	back_to_lobby_button.text = "Back to profile selection"
	back_to_lobby_button.pressed.connect(_on_back_to_lobby_pressed)
	vbox.add_child(back_to_lobby_button)

	presence_poll_timer = Timer.new()
	presence_poll_timer.wait_time = 2.0
	presence_poll_timer.one_shot = false
	presence_poll_timer.timeout.connect(_on_presence_poll_timeout)
	add_child(presence_poll_timer)

	world_poll_timer = Timer.new()
	world_poll_timer.wait_time = 2.0
	world_poll_timer.one_shot = false
	world_poll_timer.timeout.connect(_on_world_poll_timeout)
	add_child(world_poll_timer)

	position_sync_timer = Timer.new()
	position_sync_timer.wait_time = 0.15
	position_sync_timer.one_shot = false
	position_sync_timer.timeout.connect(_on_position_sync_timeout)
	add_child(position_sync_timer)


func _on_presence_poll_timeout() -> void:
	await api_client.fetch_online_users()


func _on_world_poll_timeout() -> void:
	if selected_profile_id.is_empty():
		return
	var selected_profile: Dictionary = profile_map.get(selected_profile_id, {})
	if selected_profile.is_empty():
		return
	await _refresh_world_state(selected_profile)


func _on_position_sync_timeout() -> void:
	if _position_sync_in_flight or selected_profile_id.is_empty():
		return

	var local_player: CharacterBody2D = players.get(selected_profile_id)
	if local_player == null or not is_instance_valid(local_player):
		return

	if local_player.global_position.distance_squared_to(_last_synced_position) < 0.5:
		return

	_position_sync_in_flight = true
	var result := await api_client.update_profile_position(selected_profile_id, local_player.global_position)
	if result.get("ok", false):
		_last_synced_position = local_player.global_position
	_position_sync_in_flight = false
	_update_coordinate_monitor()


func _on_presence_changed(online: Array, count: int) -> void:
	if online_label == null:
		return
	var names: PackedStringArray = []
	for item in online:
		if item is Dictionary:
			names.append(str(item.get("username", "unknown")))
	online_label.text = "Online players (%d): %s" % [count, ", ".join(names)]


func _on_back_to_lobby_pressed() -> void:
	if presence_poll_timer:
		presence_poll_timer.stop()
	if world_poll_timer:
		world_poll_timer.stop()
	if position_sync_timer:
		position_sync_timer.stop()
	await api_client.disconnect_session(selected_profile_id)
	await _show_lobby(current_account)


func _on_logout_pressed() -> void:
	if presence_poll_timer:
		presence_poll_timer.stop()
	if world_poll_timer:
		world_poll_timer.stop()
	if position_sync_timer:
		position_sync_timer.stop()
	await api_client.logout()
	if gameplay_ui_layer:
		gameplay_ui_layer.queue_free()
		gameplay_ui_layer = null
	account_label = null
	online_label = null
	coordinate_monitor_label = null
	back_to_lobby_button = null
	_clear_world()
	_show_auth_ui()


func _on_login_pressed() -> void:
	if credential_input == null:
		_set_status("Login form is unavailable")
		return

	_set_status("Logging in...")
	var login_result := await api_client.login_user(credential_input.text, password_input.text)
	if not login_result.get("ok", false):
		_show_error(login_result)
		return

	var profile_result := await api_client.fetch_profile()
	if not profile_result.get("ok", false):
		_show_error(profile_result)
		return

	await _show_lobby(profile_result["data"].get("profile", {}))


func _on_register_pressed() -> void:
	if username_input == null or email_input == null:
		_set_status("Register form is unavailable")
		return

	_set_status("Registering...")
	var register_result := await api_client.register_user(username_input.text, email_input.text, password_input.text)
	if not register_result.get("ok", false):
		_show_error(register_result)
		return

	api_client.clear_session()
	_show_auth_ui(AUTH_MODE_LOGIN, "Registration successful. Please log in.")


func _on_switch_to_register_pressed() -> void:
	_show_auth_ui(AUTH_MODE_REGISTER)


func _on_switch_to_login_pressed() -> void:
	_show_auth_ui(AUTH_MODE_LOGIN)


func _show_lobby_error(result: Dictionary) -> void:
	var error_data: Dictionary = result.get("error", {})
	if lobby_status_label:
		lobby_status_label.text = "%s: %s" % [error_data.get("code", "UNKNOWN_ERROR"), error_data.get("message", "Request failed")]


func _show_error(result: Dictionary) -> void:
	var error_data: Dictionary = result.get("error", {})
	_set_status("%s: %s" % [error_data.get("code", "UNKNOWN_ERROR"), error_data.get("message", "Request failed")])
	_show_lobby_error(result)


func _set_status(message: String) -> void:
	if status_label:
		status_label.text = message


func _clear_world() -> void:
	for player in players.values():
		if is_instance_valid(player):
			player.queue_free()
	players.clear()

	for entity in entities.values():
		if is_instance_valid(entity):
			entity.queue_free()
	entities.clear()
	_update_coordinate_monitor()


func _update_coordinate_monitor() -> void:
	if coordinate_monitor_label == null:
		return

	var local_player: CharacterBody2D = players.get(selected_profile_id)
	if local_player == null or not is_instance_valid(local_player):
		coordinate_monitor_label.text = "Position monitor: waiting for local player"
		return

	var local_position := local_player.global_position
	var distance_to_spawn := local_position.distance_to(_spawn_position)
	coordinate_monitor_label.text = "Local: (%.1f, %.1f) | Spawn: (%.1f, %.1f) | Last synced: (%.1f, %.1f) | Dist to spawn: %.1f" % [
		local_position.x,
		local_position.y,
		_spawn_position.x,
		_spawn_position.y,
		_last_synced_position.x,
		_last_synced_position.y,
		distance_to_spawn,
	]


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
		var server_position := _to_vector2(player_payload["position"])
		if player.is_local_player:
			# Client-side prediction: keep local input responsive and softly reconcile server state.
			var reconciliation_distance := player.global_position.distance_to(server_position)
			if reconciliation_distance > 96.0:
				player.global_position = server_position
			elif reconciliation_distance > 8.0:
				player.global_position = player.global_position.lerp(server_position, 0.15)
		else:
			if player.has_method("apply_network_position"):
				player.apply_network_position(server_position)
			else:
				player.global_position = server_position

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
