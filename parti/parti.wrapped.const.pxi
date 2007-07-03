cdef extern from *:
    enum MagicNumbers:
        XNone "None"
        PointerWindow
        InputFocus
        PointerRoot
        CurrentTime
        NoEventMask
        KeyPressMask
        KeyReleaseMask
        ButtonPressMask
        ButtonReleaseMask
        EnterWindowMask
        LeaveWindowMask
        PointerMotionMask
        PointerMotionHintMask
        Button1MotionMask
        Button2MotionMask
        Button3MotionMask
        Button4MotionMask
        Button5MotionMask
        ButtonMotionMask
        KeymapStateMask
        ExposureMask
        VisibilityChangeMask
        StructureNotifyMask
        ResizeRedirectMask
        SubstructureNotifyMask
        SubstructureRedirectMask
        FocusChangeMask
        PropertyChangeMask
        ColormapChangeMask
        OwnerGrabButtonMask
        KeyPress
        KeyRelease
        ButtonPress
        ButtonRelease
        MotionNotify
        EnterNotify
        LeaveNotify
        FocusIn
        FocusOut
        KeymapNotify
        Expose
        GraphicsExpose
        NoExpose
        VisibilityNotify
        CreateNotify
        DestroyNotify
        UnmapNotify
        MapNotify
        MapRequest
        ReparentNotify
        ConfigureNotify
        ConfigureRequest
        GravityNotify
        ResizeRequest
        CirculateNotify
        CirculateRequest
        PropertyNotify
        SelectionClear
        SelectionRequest
        SelectionNotify
        ColormapNotify
        ClientMessage
        MappingNotify
        LASTEvent
        PropModeReplace
        PropModePrepend
        PropModeAppend
const = {
    "XNone": XNone,
    "PointerWindow": PointerWindow,
    "InputFocus": InputFocus,
    "PointerRoot": PointerRoot,
    "CurrentTime": CurrentTime,
    "NoEventMask": NoEventMask,
    "KeyPressMask": KeyPressMask,
    "KeyReleaseMask": KeyReleaseMask,
    "ButtonPressMask": ButtonPressMask,
    "ButtonReleaseMask": ButtonReleaseMask,
    "EnterWindowMask": EnterWindowMask,
    "LeaveWindowMask": LeaveWindowMask,
    "PointerMotionMask": PointerMotionMask,
    "PointerMotionHintMask": PointerMotionHintMask,
    "Button1MotionMask": Button1MotionMask,
    "Button2MotionMask": Button2MotionMask,
    "Button3MotionMask": Button3MotionMask,
    "Button4MotionMask": Button4MotionMask,
    "Button5MotionMask": Button5MotionMask,
    "ButtonMotionMask": ButtonMotionMask,
    "KeymapStateMask": KeymapStateMask,
    "ExposureMask": ExposureMask,
    "VisibilityChangeMask": VisibilityChangeMask,
    "StructureNotifyMask": StructureNotifyMask,
    "ResizeRedirectMask": ResizeRedirectMask,
    "SubstructureNotifyMask": SubstructureNotifyMask,
    "SubstructureRedirectMask": SubstructureRedirectMask,
    "FocusChangeMask": FocusChangeMask,
    "PropertyChangeMask": PropertyChangeMask,
    "ColormapChangeMask": ColormapChangeMask,
    "OwnerGrabButtonMask": OwnerGrabButtonMask,
    "KeyPress": KeyPress,
    "KeyRelease": KeyRelease,
    "ButtonPress": ButtonPress,
    "ButtonRelease": ButtonRelease,
    "MotionNotify": MotionNotify,
    "EnterNotify": EnterNotify,
    "LeaveNotify": LeaveNotify,
    "FocusIn": FocusIn,
    "FocusOut": FocusOut,
    "KeymapNotify": KeymapNotify,
    "Expose": Expose,
    "GraphicsExpose": GraphicsExpose,
    "NoExpose": NoExpose,
    "VisibilityNotify": VisibilityNotify,
    "CreateNotify": CreateNotify,
    "DestroyNotify": DestroyNotify,
    "UnmapNotify": UnmapNotify,
    "MapNotify": MapNotify,
    "MapRequest": MapRequest,
    "ReparentNotify": ReparentNotify,
    "ConfigureNotify": ConfigureNotify,
    "ConfigureRequest": ConfigureRequest,
    "GravityNotify": GravityNotify,
    "ResizeRequest": ResizeRequest,
    "CirculateNotify": CirculateNotify,
    "CirculateRequest": CirculateRequest,
    "PropertyNotify": PropertyNotify,
    "SelectionClear": SelectionClear,
    "SelectionRequest": SelectionRequest,
    "SelectionNotify": SelectionNotify,
    "ColormapNotify": ColormapNotify,
    "ClientMessage": ClientMessage,
    "MappingNotify": MappingNotify,
    "LASTEvent": LASTEvent,
    "PropModeReplace": PropModeReplace,
    "PropModePrepend": PropModePrepend,
    "PropModeAppend": PropModeAppend,
}
