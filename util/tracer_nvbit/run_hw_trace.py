#!/usr/bin/env python3

import os
import sys
import datetime
import subprocess
from optparse import OptionParser

# Import project modules
this_directory = os.path.dirname(os.path.realpath(__file__)) + "/"
sys.path.insert(0, os.path.join(this_directory, "..", "job_launching"))
import common


def parse_args():
    parser = OptionParser()
    parser.add_option(
        "-B", "--benchmark_list", dest="benchmark_list",
        default="rodinia_2.0-ft",
        help="Comma-separated list of benchmark suites to run."
    )
    parser.add_option(
        "-D", "--device_num", dest="device_num",
        default="0",
        help="CUDA device number"
    )
    parser.add_option(
        "-n", "--norun", dest="norun", action="store_true",
        help="Only create structure, don't run benchmarks"
    )
    parser.add_option(
        "-l", "--limit_kernel_number", dest="kernel_number",
        default=-99, help="Limit number of traced kernels"
    )
    parser.add_option(
        "-t", "--terminate_upon_limit", dest="terminate_upon_limit",
        action="store_true", help="Terminate tracing after reaching kernel limit"
    )
    return parser.parse_args()


def prepare_run_dir(base_dir, device_num, cuda_version, run_name):
    run_dir = os.path.abspath(
        os.path.expandvars(
            os.path.join(base_dir, "..", "..", "hw_run", "traces", f"device-{device_num}", cuda_version, run_name)
        )
    )
    trace_dir = os.path.join(run_dir, "traces")
    os.makedirs(trace_dir, exist_ok=True)
    return run_dir, trace_dir


def link_data_dirs(run_dir, exe, ddir, this_directory):
    try:
        benchmark_data_dir = common.dir_option_test(
            os.path.join(ddir, exe, "data"), "", this_directory
        )
        data_link = os.path.join(run_dir, "data")
        if os.path.lexists(data_link):
            os.remove(data_link)
        os.symlink(benchmark_data_dir, data_link)
    except common.PathMissing:
        pass

    all_data_link = os.path.join(run_dir, "data_dirs")
    if os.path.lexists(all_data_link):
        os.remove(all_data_link)
    top_data_dir_path = common.dir_option_test(ddir, "", this_directory)
    os.symlink(top_data_dir_path, all_data_link)


def generate_run_script(run_dir, exe, args, argpair, exec_path, tracer_path, device_num, cuda_version, kernel_number, terminate_upon_limit):
    trace_folder = os.path.join(run_dir, "traces")
    sh_lines = ["set -e"]

    if terminate_upon_limit:
        sh_lines.append("export TERMINATE_UPON_LIMIT=1;")
    else:
        sh_lines.append("export TERMINATE_UPON_LIMIT=0;")

    range_val = argpair.get("sample", "")
    if range_val:
        sh_lines.append(f'export DYNAMIC_KERNEL_RANGE={range_val}')
        exec_path = f". {exec_path}"
    elif int(kernel_number) > 0:
        sh_lines.append(f'export DYNAMIC_KERNEL_RANGE="0-{kernel_number}"')
    else:
        sh_lines.append('export DYNAMIC_KERNEL_RANGE=""')

    sh_lines.extend([
        f'export CUDA_VERSION="{cuda_version}"; export CUDA_VISIBLE_DEVICES="{device_num}";',
        "rm -f traces/*",
        f'export TRACES_FOLDER={run_dir};',
        f'CUDA_INJECTION64_PATH={tracer_path}/tracer_tool.so LD_PRELOAD={tracer_path}/tracer_tool.so {exec_path} {args};',
        f'{tracer_path}/traces-processing/post-traces-processing {trace_folder};',
        f'rm -f {trace_folder}/*.trace {trace_folder}/kernelslist'
    ])

    script_path = os.path.join(run_dir, "run.sh")
    with open(script_path, "w") as f:
        f.write("\n".join(sh_lines))
    subprocess.check_call(["chmod", "u+x", script_path])

def generate_inner_run_script(
    run_dir,
    exec_inside_container_path,
    args,
    tracer_path,
    trace_dir,
    device_num,
    cuda_version,
    kernel_number,
    terminate_upon_limit,
    argpair,
):
    script_path = os.path.join(run_dir, "run_script_inside_container.sh")

    lines = ["#!/bin/bash", "set -e"]

    if terminate_upon_limit:
        lines.append("export TERMINATE_UPON_LIMIT=1")
    else:
        lines.append("export TERMINATE_UPON_LIMIT=0")

    range_val = argpair.get("sample", "")
    if range_val:
        lines.append(f'export DYNAMIC_KERNEL_RANGE="{range_val}"')
    elif int(kernel_number) > 0:
        lines.append(f'export DYNAMIC_KERNEL_RANGE="0-{kernel_number}"')
    else:
        lines.append('export DYNAMIC_KERNEL_RANGE=""')

    lines += [
        f'export CUDA_VERSION="{cuda_version}"',
        f'export CUDA_VISIBLE_DEVICES="{device_num}"',
        'export TRACES_FOLDER="/workspace/traces"',
        'rm -f ${TRACES_FOLDER}/*',
        f'chmod +x {exec_inside_container_path}',
        f'CUDA_INJECTION64_PATH=/workspace/util/tracer_nvbit/tracer_tool/tracer_tool.so \\',
        f'LD_PRELOAD=/workspace/util/tracer_nvbit/tracer_tool/tracer_tool.so {exec_inside_container_path} {args}',
        f'/workspace/util/tracer_nvbit/tracer_tool/traces-processing/post-traces-processing /workspace/traces',
        'rm -f /workspace/traces/*.trace /workspace/traces/kernelslist'
    ]


    with open(script_path, "w") as f:
        f.write("\n".join(lines))

    subprocess.check_call(["chmod", "u+x", script_path])
    return os.path.basename(script_path)
def generate_run_in_container_script(
    run_dir,
    docker_builder,
    tracer_git_url,
    script_inside_container_name,
    exec_path,
):
    script_path = os.path.join(run_dir, "run_in_container.sh")
    exec_inside_container_path = "/workspace/my_app"

    script_lines = [
        "#!/bin/bash",
        "set -e",
        "",
        "# Start the container and extract the container ID",
        f'CONTAINER_ID=$({docker_builder} "{run_dir}" | grep -m1 "^ID=" | cut -d"=" -f2)',
        'echo "Started container with ID: $CONTAINER_ID"',
        "",
        "# Clone tracer repo and build tracer inside container",
        f'docker exec $CONTAINER_ID git clone {tracer_git_url} /workspace || echo "Tracer repo already exists"',
        'docker exec $CONTAINER_ID bash -c "cd /workspace/util/tracer_nvbit && ./install_nvbit.sh && make -j"',

        "# Copy executable and run script into container",
        f'docker cp {exec_path} $CONTAINER_ID:/workspace/my_app',
        f'docker cp {os.path.join(run_dir, script_inside_container_name)} $CONTAINER_ID:/workspace/{script_inside_container_name}',
        "",
        "# Run tracing inside container",
        f'docker exec $CONTAINER_ID bash /workspace/{script_inside_container_name}',
        "",
        "# Stop and remove container",
        'echo "Tracing complete. Stopping container..."',
        'docker stop $CONTAINER_ID',
        'docker rm $CONTAINER_ID'
    ]

    with open(script_path, "w") as f:
        f.write("\n".join(script_lines))

    subprocess.check_call(["chmod", "u+x", script_path])

def main():
    options, _ = parse_args()
    common.load_defined_yamls()

    benchmarks = common.gen_apps_from_suite_list(options.benchmark_list.split(","))
    cuda_version = common.get_cuda_version(this_directory)
    tracer_path = os.path.join(this_directory, "tracer_tool")

    for bench in benchmarks:
        edir, ddir, docker_builder, exe, argslist = bench

        for argpair in argslist:
            args = argpair.get("args", "")
            run_name = os.path.join(exe, common.get_argfoldername(args))
            run_dir = os.path.abspath(
                os.path.expandvars(
                    os.path.join(
                        this_directory,
                        "..", "..", "hw_run", "traces",
                        f"device-{options.device_num}", cuda_version, run_name
                    )
                )
            )
            trace_dir = os.path.join(run_dir, "traces")
            os.makedirs(trace_dir, exist_ok=True)

            link_data_dirs(run_dir, exe, ddir, this_directory)

            exec_path = common.file_option_test(os.path.join(edir, exe), "", this_directory)

            if docker_builder:
                exec_inside_container_path = "/workspace/my_app"

                inner_script_name = generate_inner_run_script(
                    run_dir,
                    exec_inside_container_path,
                    args,
                    tracer_path,
                    trace_dir,
                    options.device_num,
                    cuda_version,
                    options.kernel_number,
                    options.terminate_upon_limit,
                    argpair
                )

                tracer_git_url = "https://github.com/accel-sim/accel-sim-framework.git"  # Replace this
                generate_run_in_container_script(
                    run_dir,
                    docker_builder,
                    tracer_git_url,
                    inner_script_name,
                    exec_path
                )

                # If not --norun, run the container script
                if not options.norun:
                    saved_dir = os.getcwd()
                    os.chdir(run_dir)
                    print(f"Running containerized benchmark for {exe} in {run_dir}")
                    if subprocess.call(["bash", "run_in_container.sh"]) != 0:
                        sys.exit(f"Error tracing in container for {run_dir}")
                    os.chdir(saved_dir)

            else:
                generate_run_script(
                    run_dir,
                    exec_path,
                    args,
                    tracer_path,
                    trace_dir,
                    options.device_num,
                    cuda_version,
                    options.kernel_number,
                    options.terminate_upon_limit,
                    argpair
                )

                if not options.norun:
                    saved_dir = os.getcwd()
                    os.chdir(run_dir)
                    print(f"Running native benchmark for {exe} in {run_dir}")
                    if subprocess.call(["bash", "run.sh"]) != 0:
                        sys.exit(f"Error tracing natively in {run_dir}")
                    os.chdir(saved_dir)

if __name__ == "__main__":
    main()
