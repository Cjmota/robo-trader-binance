def to_native(value):

    import numpy as np

    if isinstance(value, (np.floating,)):
        return float(value)

    if isinstance(value, (np.integer,)):
        return int(value)

    if isinstance(value, (np.bool_,)):
        return bool(value)

    return value