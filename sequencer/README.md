---
title: Timer Plugin
layout: default
summary: Plugin for monostable multi vibrators and countdowns
---

# Configuration

## plugin.conf

<pre>
[Timer]
   class_name = Timer
   class_path = plugins.timer
</pre>

## items.conf

timer_mode
timer_len
timer_countdown
timer_trigger

### timer_mode

Determines the mode of the timer. The following modes are possible:
oneshot - timer runs until it expires or it is canceled
oneshot_retrig - timer runs until it expires or it is canceled; the timer
can be restarted while running

### timer_len

Specifies the length of a timer run in seconds

### timer_countdown

Marks the item as the countdown item for the timer item given via its path.
Type must be num

### timer_trigger

Marks the item as the expire item for the timer item given via its path.
Type must be true.
Value is set to 1 (true) if the timer expires or 0 (false) if the timer is canceled.

### Example

Please provide an item configuration with every attribute and usefull settings.

<pre>
# items/my.conf

[timer]
    [[selfdestruction]]
        type = bool
        timer_mode = oneshot
	timer_len = 120
	[[[countdown]]]
	    type = num
	    timer_countdown = timer.selfdestruction
        [[[expired]]]
	    type = bool
	    timer_trigger = timer.selfdestruction

</pre>

## logic.conf
If your plugin support item triggers as well, please describe the attributes like the item attributes.


# Methodes
If your plugin provides methods for logics. List and describe them here...

## method1(param1, param2)
This method enables the logic to send param1 and param2 to the device. You could call it with `sh.my.method1('String', 2)`.

## method2()
This method does nothing.
