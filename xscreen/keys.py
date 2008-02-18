def mask_to_names(mask, modifier_map):
    modifiers = []
    for modifier in ["shift", "control",
                     "meta", "super", "hyper", "alt",
                     ]
        modifier_mask = modifier_map[modifier]
        if modifier_mask & mask:
            modifiers.append(modifier_mask)
    return modifiers
