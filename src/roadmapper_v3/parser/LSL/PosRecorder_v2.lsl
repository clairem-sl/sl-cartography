// This Source Code Form is subject to the terms of the Mozilla Public
// License, v. 2.0. If a copy of the MPL was not distributed with this
// file, You can obtain one at https://mozilla.org/MPL/2.0/.

// Help for this HUD is available at:
// https://rentry.co/posrecorder-v2-howto

// PLEASE ONLY RUN THIS IN MONO, NOT IN LSO!


// #################### Configurables

float RECORD_EVERY_S = 2.0;
float CHECK_EVERY_S = 0.25;


// #################### Other constants

integer OTHMENU_MAIN = (integer)-8008135;
integer OTHMENU_SETDESC = (integer)-80081351;
integer OTHMENU_SETCOL = (integer)-80081352;
integer OTHMENU_RECSPD = (integer)-80081353;


// #################### HUD Interface

string BTN_TEXTU = "1b937953-237c-22c9-d04b-da3811f23e88";
vector BTN_SCALE = <0.125, 0.125, 0.0>;

// X-pos of button textures. RDY, ON, DIS
list BTN_X = [-0.435, -0.310, -0.185];

integer FACE_REC = 0;
integer FACE_POS = 2;
integer FACE_BRK = 4;
integer FACE_ARC = 6;
integer FACE_CONTI = 1;
integer FACE_ROUTE = 3;
integer FACE_BRUSH = 5;
integer FACE_OTHER = 7;

// Y-pos of button textures. Use above to determine which is which
//             REC    CONTI   POS    ROUTE   BRK    BRUSH   ARC    OTHER
list BTN_Y = [0.435, -0.065, 0.310, -0.190, 0.185, -0.315, 0.060, -0.440];

// Again, remember the order: [REC, CONTI, POS, ROUTE, BRK, BRUSH, ARC, OTHER]
UpdBtnAll(list NewStates) {
    integer FaceNum;
    float BtnX;
    float BtnY;
    list Params = [];
    for (FaceNum = 0; FaceNum <= 7; ++FaceNum) {
        BtnX = llList2Float(BTN_X, llList2Integer(NewStates, FaceNum));
        BtnY = llList2Float(BTN_Y, FaceNum);
        Params += [ PRIM_TEXTURE, FaceNum, BTN_TEXTU, BTN_SCALE, <BtnX, BtnY, 0.0>, 0.0 ];
    }
    llSetLinkPrimitiveParamsFast(0, Params);
}


// #################### Global States

key gOwnerID;
integer gGreeted = FALSE;
integer gArcPoints;
float gLastRecTime;
integer gListener;
string gBrush = "SOLID";
integer gRecording = FALSE;
string gWantSet;
float gEnterRecordingState;

list gOtherCmds = ["--", "--", "Cancel", "GetSLURL", "--", "RecSpeed", "SetDesc(S)", "SetColor(R)", "EndRoute"];


// #################### Logic


RecordPos() {
    vector Pos = llGetPos();
    string regName = llGetRegionName();
    string parcelName = llList2String(llGetParcelDetails(Pos, [PARCEL_DETAILS_NAME]) ,0);
    vector regCorner = llGetRegionCorner();
    string message =
        "3;;" +  // "3" is the DATA_Version
        regName + ";;" + parcelName + ";;<" +
        (string)((integer)(regCorner.x)) + ", " +
        (string)((integer)(regCorner.y)) + ", " +
        "0>;;" +  // Region Corners always have 'z' set to 0, so no need for conversion
        (string)Pos
        ;
    llOwnerSay(message);
    return;
}

GetSLURLNavHead() {
    llRegionSayTo(gOwnerID, 0, "# SLURL of current location:");
    vector Pos = llGetPos();
    llRegionSayTo(
        gOwnerID, 0,
        "# http://maps.secondlife.com/secondlife/" + llEscapeURL(llGetRegionName()) +
        "/" + (string)((integer)Pos.x) +
        "/" + (string)((integer)Pos.y) +
        "/" + (string)((integer)Pos.z)
    );
    vector EulerRot = llRot2Euler(llGetRootRotation());
    // Need to do this because SL Heading 000 is to the East, and North is 090 (ccw, opposite aviation)
    integer Heading = (integer)(90.0 - (EulerRot.z * RAD_TO_DEG)) % 360;
    while (Heading < 0) Heading += 360;
    string NavHeading = llGetSubString("00" + (string)Heading, -3, -1);
    llRegionSayTo(gOwnerID, 0, "# With NAV Heading: " + NavHeading);
}

TimedOut() {
    llSetTimerEvent(0);
    llListenRemove(gListener);
    llRegionSayTo(gOwnerID, 0, "# Timed out waiting for response");
}

// #################### State Machines

default {
    on_rez(integer start_param) {
        llResetScript();
    }

    state_entry() {
        llSetTimerEvent(0);
        gOwnerID = llGetOwner();
        if (!gGreeted) {
            llRegionSayTo(gOwnerID, 0, "# PosRecorder v2.1 powered on.");
            llRegionSayTo(gOwnerID, 0, "# RecSpeed = " + (string)RECORD_EVERY_S + ", PollSpeed = " + (string)CHECK_EVERY_S);
            gGreeted = TRUE;
        }
        UpdBtnAll([0, 0, 0, 0, 0, 0, 0, 0]);
        gRecording = FALSE;
        gBrush = "SOLID";
        llRegionSayTo(gOwnerID, 0, "# Ready. " + (string)llGetUsedMemory() + " bytes used.");
    }

    touch_end(integer total_number) {
        integer linknum = llDetectedLinkNumber(0);
        integer facenum = llDetectedTouchFace(0);
        if (facenum == FACE_REC) {
            gEnterRecordingState = llGetTime();
            state recording;
        } else if (facenum == FACE_POS) {
            RecordPos();
        } else if (facenum == FACE_BRK) {
            llOwnerSay("break");
            gBrush = "SOLID";
        } else if (facenum == FACE_ARC) {
            state arcrecord;
        } else if (facenum == FACE_CONTI) {
            gWantSet = "continent";
            state set_contiroute;
        } else if (facenum == FACE_ROUTE) {
            gWantSet = "route";
            state set_contiroute;
        } else if (facenum == FACE_BRUSH) {
            state set_brush;
        } else if (facenum == FACE_OTHER) {
            state other_cmds;
        }
    }
}

state recording {
    state_entry() {
        UpdBtnAll([1, 2, 0, 2, 0, 0, 0, 2]);
        llOwnerSay("# Recording begins");
        gRecording = TRUE;
        RecordPos();
        gLastRecTime = llGetTime();
        llSetTimerEvent(CHECK_EVERY_S);
    }

    timer() {
        if ((llGetTime() - gLastRecTime) > RECORD_EVERY_S) {
            gLastRecTime = llGetTime();
            RecordPos();
        }
    }

    touch_end(integer total_number) {
        integer facenum = llDetectedTouchFace(0);

        integer idx = llListFindList([FACE_POS, FACE_BRUSH, FACE_BRK, FACE_ARC, FACE_REC], [facenum]);
        if (idx == (integer)-1) {
            llRegionSayTo(gOwnerID, 0, "# Button " + (string)facenum + " is currently disabled.");
            return;
        }

        RecordPos();
        if (facenum == FACE_POS) return;

        // From this point onwards, state will change. So the timer event here will be out of scope.
        // But we stop timer event anyways so if the target state has a timer() event, it will not get
        // inadvertently triggered by this state's short timer period.
        llSetTimerEvent(0);

        if (facenum == FACE_BRUSH) {
            llRegionSayTo(gOwnerID, 0, "# Trying to change brush...");
            state set_brush;
        }

        // From this point onwards, recording is stopped. Let's reflect that in the global status var.
        gRecording = FALSE;

        if (facenum == FACE_REC) {
            if ((llGetTime() - gEnterRecordingState) < 3.0) {
                llRegionSayTo(gOwnerID, 0, "# Ignoring double-click on Rec.");
                gRecording = TRUE;
                return;
            }
            llRegionSayTo(gOwnerID, 0, "# Stopping recording...");
            state default;
        }

        // Finally, from this point onwards, 'break' is implied.
        llOwnerSay("break");
        gBrush = "SOLID";

        if (facenum == FACE_BRK) {
            llRegionSayTo(gOwnerID, 0, "# Stop & break recording...");
            state default;
        }

        if (facenum == FACE_ARC) {
            llRegionSayTo(gOwnerID, 0, "# Change to arc mode...");
            state arcrecord;
        }
    }
}

state arcrecord {
    state_entry() {
        UpdBtnAll([2, 2, 0, 2, 2, 2, 1, 2]);
        llRegionSayTo(gOwnerID, 0, "# Arc mode. Recording arc startpoint.");
        RecordPos();
        gArcPoints = 1;
        gBrush = "SOLID";

        llRegionSayTo(gOwnerID, 0, "# Now please move to somewhere in the middle of the arc, and press Pos");
    }

    touch_end(integer total_number) {
        integer linknum = llDetectedLinkNumber(0);
        integer facenum = llDetectedTouchFace(0);
        if (facenum == FACE_POS) {
            RecordPos();
            if (++gArcPoints == 3) {
                llRegionSayTo(gOwnerID, 0, "# Arc points complete. Breaking & stopping...");
                llOwnerSay("break");
                gBrush = "SOLID";
                state default;
            }
            llRegionSayTo(gOwnerID, 0, "# Arc middlepoint recorded.");
            llRegionSayTo(gOwnerID, 0, "# Now please move to the end of the arc and press Pos");
        } else if (facenum == FACE_ARC) {
            llRegionSayTo(gOwnerID, 0, "# Cannot cancel Arc mode");
        } else {
            llRegionSayTo(gOwnerID, 0, "# Button " + (string)facenum + " is currently disabled.");
        }
    }
}

state set_contiroute {
    state_entry() {
        if (gWantSet == "continent") UpdBtnAll([2, 1, 2, 2, 2, 2, 2, 2]);
        else UpdBtnAll([2, 2, 2, 1, 2, 2, 2, 2]);
        llRegionSayTo(gOwnerID, 0, "# Setting " + gWantSet + " requested.");

        gListener = llListen((integer)-8008135, "", gOwnerID, "");
        llTextBox(
            gOwnerID,
            "Please enter " + gWantSet + " name (case-sensitive), leave empty to cancel.",
            (integer)-8008135
        );
        llSetTimerEvent(60);
    }

    listen(integer channel, string name, key id, string message) {
        llListenRemove(gListener);
        llSetTimerEvent(0);
        message = llStringTrim(message, STRING_TRIM);
        if (message) llOwnerSay(gWantSet + ": " + message);
        else llRegionSayTo(gOwnerID, 0, "# Empty name, cancelled");

        state default;
    }

    touch_end(integer num_detected) {
        integer facenum = llDetectedTouchFace(0);
        if (
            (facenum == FACE_CONTI && gWantSet == "continent")
            ||
            (facenum == FACE_ROUTE && gWantSet == "route")
            )
            {
                llSetTimerEvent(0);
                llListenRemove(gListener);
                llRegionSayTo(gOwnerID, 0, "# Set " + gWantSet + " cancelled");
                state default;
            }
        llRegionSayTo(gOwnerID, 0, "# Button " + (string)facenum + " is disabled.");
    }

    timer() {
        TimedOut();
        state default;
    }
}

state set_brush {
    state_entry() {
        if (gRecording) UpdBtnAll([1, 2, 2, 2, 2, 1, 2, 2]);
        else UpdBtnAll([2, 2, 2, 2, 2, 1, 2, 2]);
        llRegionSayTo(gOwnerID, 0, "# Setting brush requested.");

        gListener = llListen((integer)-8008135, "", gOwnerID, "");
        llDialog(
            gOwnerID,
            "Choose a brush:",
            ["ARROW2", "ARROW1", "Cancel", "SOLID", "DASHED", "RAILS"],
            (integer)-8008135
        );
        llSetTimerEvent(60);
    }

    listen(integer channel, string name, key id, string message) {
        if (message == "--") return;
        llSetTimerEvent(0);
        llListenRemove(gListener);
        if (message == "Cancel") {
            llRegionSayTo(gOwnerID, 0, "# Brush selection cancelled");
        } else {
            if (message == gBrush) {
                llRegionSayTo(gOwnerID, 0, "# Same brush, cancelling");
            } else {
                if (gRecording) llOwnerSay("break");
                if (message == "ARROW1") {
                    llRegionSayTo(gOwnerID, 0, "# IMPORTANT: ARROW1 chosen, so arrow will be drawn at the last Pos only!");
                }
                llOwnerSay("mode: " + message);
            }
        }
        if (gRecording) state recording;
        else state default;
    }

    touch_end(integer num_detected) {
        integer facenum = llDetectedTouchFace(0);
        if (facenum == FACE_BRUSH) {
            llSetTimerEvent(0);
            llListenRemove(gListener);
            llRegionSayTo(gOwnerID, 0, "# Brush selection cancelled");
            if (gRecording) state recording;
            else state default;
        }
        llRegionSayTo(gOwnerID, 0, "# Button " + (string)facenum + " is disabled.");
    }

    timer() {
        TimedOut();
        state default;
    }
}

state other_cmds {
    state_entry() {
        UpdBtnAll([2, 2, 2, 2, 2, 2, 2, 1]);
        llRegionSayTo(gOwnerID, 0, "# Other commands.");

        gListener = llListen(OTHMENU_MAIN, "", gOwnerID, "");
        llDialog(gOwnerID, "Choose command", gOtherCmds, OTHMENU_MAIN);
        llSetTimerEvent(60);
    }

    listen(integer channel, string name, key id, string message) {
        if (message == "--") {
            llDialog(gOwnerID, "Choose command", gOtherCmds, OTHMENU_MAIN);
            return;
        }
        llSetTimerEvent(0);
        llListenRemove(gListener);
        if (channel == OTHMENU_MAIN) {
            if (message == "Cancel") {
                llRegionSayTo(gOwnerID, 0, "# Other commands cancelled");
                state default;
            }
            else if (message == "GetSLURL") {
                GetSLURLNavHead();
                state default;
            }
            else if (message == "EndRoute") {
                llOwnerSay("endroute");
                llRegionSayTo(gOwnerID, 0, "# 'endroute' has been indicated");
                llRegionSayTo(gOwnerID, 0, "# You *must* use the Route button again before recording new positions!");
                state default;
            }
            else if (message == "SetDesc(S)") {
                gListener = llListen(OTHMENU_SETDESC, "", gOwnerID, "");
                llTextBox(gOwnerID, "Please enter Segment description, leave empty to cancel", OTHMENU_SETDESC);
            }
            else if (message == "SetColor(R)") {
                gListener = llListen(OTHMENU_SETCOL, "", gOwnerID, "");
                llTextBox(gOwnerID, "Please enter desired RGB, comma- or space-separated. Empty = cancel.", OTHMENU_SETCOL);
            }
            else if (message == "RecSpeed") {
                gListener = llListen(OTHMENU_RECSPD, "", gOwnerID, "");
                llTextBox(gOwnerID, "Enter desired recording speed, must be a multiple of 0.25", OTHMENU_RECSPD);
            }
            llSetTimerEvent(60);
            return;
        }
        message = llStringTrim(message, STRING_TRIM);
        if (channel == OTHMENU_SETDESC) {
            if (message) llOwnerSay("segdesc: " + message);
            else llRegionSayTo(gOwnerID, 0, "# Segment description cancelled");
        }
        else if (channel == OTHMENU_SETCOL) {
            if (message) llOwnerSay("color: " + message);
            else llRegionSayTo(gOwnerID, 0, "# RGB color cancelled");
        }
        else if (channel == OTHMENU_RECSPD) {
            if (message) {
                RECORD_EVERY_S = (float)message;
                llRegionSayTo(gOwnerID, 0, "# RecSpeed set to " + message + " seconds.");
            }
            else llRegionSayTo(gOwnerID, 0, "# RecSpeed cancelled");
        }
        state default;
    }

    timer() {
        TimedOut();
        state default;
    }
}
