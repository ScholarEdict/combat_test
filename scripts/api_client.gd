extends Node
class_name ApiClient

signal authenticated(profile: Dictionary, assets: Dictionary)

const SESSION_PATH := "user://session.cfg"
const WEB_SESSION_STORAGE_KEY := "combat_test_auth_token"

@export var base_url := "http://127.0.0.1:8080"

var session_token := ""
var profile: Dictionary = {}
var assets: Dictionary = {}

func _ready() -> void:
	load_session()


func has_session() -> bool:
	return not session_token.is_empty()


func load_session() -> void:
	if _is_web_runtime() and Engine.has_singleton("JavaScriptBridge"):
		session_token = _web_session_get(WEB_SESSION_STORAGE_KEY)
		return

	var cfg := ConfigFile.new()
	if cfg.load(SESSION_PATH) == OK:
		session_token = str(cfg.get_value("auth", "token", ""))


func clear_session() -> void:
	session_token = ""
	if _is_web_runtime() and Engine.has_singleton("JavaScriptBridge"):
		_web_session_set(WEB_SESSION_STORAGE_KEY, "")
		return

	var cfg := ConfigFile.new()
	cfg.set_value("auth", "token", "")
	cfg.save(SESSION_PATH)


func register_user(username: String, email: String, password: String) -> Dictionary:
	var response := await _request_json("/auth/register", HTTPClient.METHOD_POST, {
		"username": username,
		"email": email,
		"password": password,
	})
	if response.get("ok", false):
		_apply_session(response)
	return response


func login_user(credential: String, password: String) -> Dictionary:
	var response := await _request_json("/auth/login", HTTPClient.METHOD_POST, {
		"credential": credential,
		"password": password,
	})
	if response.get("ok", false):
		_apply_session(response)
	return response


func fetch_profile() -> Dictionary:
	var response := await _request_json("/profile/me", HTTPClient.METHOD_GET)
	if response.get("ok", false):
		profile = response["data"].get("profile", {})
		assets = response["data"].get("assets", {})
		emit_signal("authenticated", profile, assets)
	return response


func push_state(player_state: Dictionary) -> Dictionary:
	return await _request_json("/state/update", HTTPClient.METHOD_POST, {
		"player_state": player_state,
	})


func fetch_world_state() -> Dictionary:
	return await _request_json("/state/world", HTTPClient.METHOD_GET)


func _apply_session(response: Dictionary) -> void:
	session_token = str(response["data"].get("session", {}).get("token", ""))

	if _is_web_runtime() and Engine.has_singleton("JavaScriptBridge"):
		_web_session_set(WEB_SESSION_STORAGE_KEY, session_token)
		return

	var cfg := ConfigFile.new()
	cfg.set_value("auth", "token", session_token)
	cfg.save(SESSION_PATH)


func _request_json(path: String, method: HTTPClient.Method, body: Dictionary = {}) -> Dictionary:
	var request := HTTPRequest.new()
	add_child(request)

	var headers := PackedStringArray(["Content-Type: application/json"])
	if has_session():
		headers.append("Authorization: Bearer %s" % session_token)

	var serialized_body := ""
	if method != HTTPClient.METHOD_GET:
		serialized_body = JSON.stringify(body)

	var req_err := request.request(base_url + path, headers, method, serialized_body)
	if req_err != OK:
		request.queue_free()
		return _error("NETWORK_ERROR", "Failed to send request")

	var result: Array = await request.request_completed
	request.queue_free()
	var http_result := int(result[0])
	var response_code := int(result[1])
	var raw_body := PackedByteArray(result[3]).get_string_from_utf8()

	if http_result != HTTPRequest.RESULT_SUCCESS:
		return _error("NETWORK_ERROR", "Network request failed")

	var parsed = JSON.parse_string(raw_body)
	if typeof(parsed) != TYPE_DICTIONARY:
		return _error("BAD_RESPONSE", "Server returned invalid JSON")

	var response: Dictionary = parsed
	if response.get("ok", false):
		return response

	if not response.has("error"):
		return _error("REQUEST_FAILED", "HTTP %s" % response_code)
	return response


func _is_web_runtime() -> bool:
	return OS.has_feature("web")


func _web_session_get(key: String) -> String:
	var script := "sessionStorage.getItem(%s) || '';" % JSON.stringify(key)
	var value = JavaScriptBridge.eval(script, true)
	return str(value)


func _web_session_set(key: String, value: String) -> void:
	var script := "if (%s === '') { sessionStorage.removeItem(%s); } else { sessionStorage.setItem(%s, %s); }" % [
		JSON.stringify(value),
		JSON.stringify(key),
		JSON.stringify(key),
		JSON.stringify(value),
	]
	JavaScriptBridge.eval(script)


func _error(code: String, message: String) -> Dictionary:
	return {
		"ok": false,
		"error": {
			"code": code,
			"message": message,
		}
	}
