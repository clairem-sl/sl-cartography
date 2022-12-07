# PosRecorder v2

This script is supposed to go into a HUD that is constructed in the following way:

> First, grab the [free full-perm 8-face display panel component on the
> MarketPlace](https://marketplace.secondlife.com/p/Eight-face-display-panels/11026621).
> 
> Rez it, and attach it to your HUD. You will need to rotate it in such a way that
> it is full-frontal to you, with "face 0" on top left and "face 1" on top right.
> 
> Then, you just add the `PosRecorder_v2.lsl` script into the panel, and as the
> script starts up, it will pull the necessary texture (created and uploaded by me)
> to 'populate' the HUD with button representation.
> 
> Finally, make sure that the finished HUD is marked as "No Transfer" for the
> "Next Owner" -- that is the stipulated licensing requirement of the 8-face display
> panel. (Actually, you can make it, like, just "No Mod" or "No Copy", but those two
> are much less palatable in Second Life, for many reasons I won't explain here.)
> 
> And... that's it, actually. The HUD should be immediately usable.
> 
> For the user manual (on how to actually use/operate the HUD), check my Rentry page:
> 
> https://rentry.co/posrecorder-v2-howto

With that out of the way, I decided to include this script here because the
PosRecorder v2 script's behavior tracks exactly the requirements of the Chat Parser
in `chat.py`. By placing the script here, I can easily update the script if I add
new features to / change existing behaviors of the RoadMapper.

ALSO...

I had a blast editing LSL files using PyCharm by utilizing the following:

https://github.com/clairem-sl/jetbrains-lsl-support

(It's a fork of [another repo](https://github.com/aglaia-resident/jetbrains-lsl-support).)

So by keeping the file close to the Python files with which it interacts (indirectly)
I can keep the file up-to-date using PyCharm as well!


## The Texture

The texture is a 512x512 px texture.

Divided into 8 rows, each row (64-pixel height) corresponds to a face of the
previously-mention 8-face display panel. For actual correlation, see the
`FACE_*` and `BTN_Y` constants in the script.

Each row is further divided into eight 64-pixel columns, although only three leftmost
columns are used. The columns hold the images for a button in the READY, ON/ACTIVE,
and DISABLED states, respectively. (See the `BTN_X` constant in the script).
