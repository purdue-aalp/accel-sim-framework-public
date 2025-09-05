import re
import argparse

parser = argparse.ArgumentParser(description='Process trace file to remove spinloops')
parser.add_argument('--file_path', '-f', type=str, help='Path to the trace file')
args = parser.parse_args()

file_path = args.file_path


# file_path = "kernel-5-tb46_0_1.traceg"
# file_path = "kernel-5-ctx_0x64b7a1d89500.traceg"

processed_file_path = file_path.replace('.traceg', '_processed.traceg')

last_warp_id = 0

drop_inst = False

warp_inst = []

warp_inst_ct = 0

with open(file_path, 'r') as f, open(processed_file_path, 'w') as f_processed:
    line_num = 0
    for line in f:
        # search for opcode (4 hex digits) and active mask (8 hex digits)
        is_inst = re.search(r'([0-9a-fA-F]{4}) ([0-9a-fA-F]{8})', line)

        if is_inst:
            if "0 BRA 0 0 13104" in line:
                # branch control of the spinloop
                active_mask = is_inst.group(2)
                if active_mask == 'ffffffff':
                    drop_inst = True
                elif active_mask == '00000000':
                    drop_inst = False
            if drop_inst:
                # drop the inst
                continue
            else:
                warp_inst_ct += 1
                warp_inst.append(line)
        
        elif "warp = " in line:
            # previous warp end
            if warp_inst_ct != 0:
                # if not first warp
                # write out the insts with the inst ct
                f_processed.write(f'insts = {warp_inst_ct}\n')
                for inst in warp_inst:
                    f_processed.write(inst)

            warp_inst = []
            warp_inst_ct = 0
            drop_inst = False
            f_processed.write(line)
        elif "END_TB" in line:
            # also end of a warp
            # dump warp inst
            f_processed.write(f'insts = {warp_inst_ct}\n')
            for inst in warp_inst:
                f_processed.write(inst)

            warp_inst = []
            warp_inst_ct = 0
            drop_inst = False
            f_processed.write(line)
        elif "insts = " in line:
            continue
        else:
            f_processed.write(line)
        line_num += 1