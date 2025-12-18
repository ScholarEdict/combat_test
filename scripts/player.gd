extends CharacterBody2D

@export var speed := 100.0
var last_dir = Vector2.DOWN
@onready var anim = $AnimatedSprite2D
var radius = 15
@onready var sanim = $sword/AnimationPlayer

func _physics_process(delta: float) -> void:
	print(global_position)
	get_movement()
	move_and_slide()
	follow_aim()
	sync_anim()

func _ready() -> void:
	add_to_group("player")

# Called every frame. 'delta' is the elapsed time since the previous frame.
func _process(delta: float) -> void:
	sword_rotate()
	sword_anim()

func get_movement():
	var input_dir = Input.get_vector("A", "D", "W", "S") 
	if input_dir != Vector2.ZERO:
		velocity = input_dir*speed
	else:
		velocity = Vector2.ZERO

func sync_anim():
	if velocity != Vector2.ZERO:
		get_walk_anim()
	else:
		get_idle_anim()

func follow_aim():
	var dir = get_global_mouse_position() - global_position
	if dir.length_squared() > 0.0001:
		last_dir = dir.normalized()


func get_walk_anim():
	anim.flip_h = last_dir.x < 0
	if anim.animation != "walk":
		anim.play("walk")


func get_idle_anim():
	anim.flip_h = last_dir.x < 0
	if anim.animation != "idle":
		anim.play("idle")


func sword_rotate():
	var dir = (get_global_mouse_position() - global_position).normalized()
	$sword.position = dir*radius
	$sword.rotation = dir.angle()

func sword_anim()->void:
	if Input.is_action_just_pressed("click"):
		sanim.play("swing")
		
func spawn_enemy():
	var enemy = preload("res://scenes/enemies.tscn").instantiate()
	enemy.player = self
	get_parent().add_child(enemy)
