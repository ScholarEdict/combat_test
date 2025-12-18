class_name Hurtbox
extends Area2D

func _init()->void:
	collision_layer = 0
	collision_mask = 2	

# Called when the node enters the scene tree for the first time.
func _ready() -> void:
	area_entered.connect(_on_area_entered)

# Called every frame. 'delta' is the elapsed time since the previous frame.
func _process(delta: float) -> void:
	pass

func _on_area_entered(hitbox: Hitbox):	
	if hitbox == null:
		return
	if owner.has_method("play_anim"):
		owner.play_anim()
		
	var attacker = hitbox.owner
	var direction:Vector2 = (owner.global_position - attacker.global_position).normalized()
	
	if owner.has_method("apply_knockback"):
		owner.apply_knockback(direction, 5, 0.1)	
