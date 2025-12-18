class_name Hitbox
extends Area2D

func _init()->void:
	collision_layer = 2 
	collision_mask = 0

# Called when the node enters the scene tree for the first time.
func _ready() -> void:
	pass

# Called every frame. 'delta' is the elapsed time since the previous frame.
func _process(delta: float) -> void:
	pass
