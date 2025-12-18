extends CharacterBody2D

@onready var anim := $AnimationPlayer
@onready var player := get_tree().get_nodes_in_group("player")[0]
var speed: float = 50.0
var knockback: Vector2 = Vector2.ZERO
var knockback_timer: float = 0.0

# Called when the node enters the scene tree for the first time.
func _ready() -> void:
	pass # Replace with function body.

func _physics_process(delta: float) -> void:
	if knockback_timer>0:
		position += knockback
		knockback_timer-=delta
	else:
		_movement(delta)
	move_and_slide()
			
func _movement(delta:float)->void:
	if player:
		var direction = (player.global_position - global_position).normalized()
		velocity = direction*speed
	
# Called every frame. 'delta' is the elapsed time since the previous frame.
func _process(delta: float) -> void:
	pass	
func play_anim():
	anim.play("got_attack")

func apply_knockback(direction: Vector2, force:float, knockback_dur: float)->void:
	knockback = direction*force
	knockback_timer = knockback_dur
	
	
