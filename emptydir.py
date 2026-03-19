"""emptydir — dekube transform.

Auto-detects emptyDir volumes shared between init/sidecar/main containers
of the same pod and replaces anonymous Compose volumes with shared named
volumes. Runs early (priority 1000) so downstream transforms see the
corrected volume entries.
"""

import sys

_WORKLOAD_KINDS = ("DaemonSet", "Deployment", "Job", "Pod", "StatefulSet")


def _emptydir_log(msg):
    print(f"  [emptydir] {msg}", file=sys.stderr)


def _find_shared_emptydirs(manifests):
    """Scan workload manifests for emptyDir volumes mounted by 2+ containers.

    Returns: {workload_name: {vol_name: {compose_svc_name: mount_path}}}
    """
    result = {}
    for kind in _WORKLOAD_KINDS:
        for m in manifests.get(kind, []):
            name = (m.get("metadata") or {}).get("name", "unknown")
            spec = m.get("spec") or {}
            if kind == "Pod":
                pod_spec = spec
            else:
                pod_spec = (spec.get("template") or {}).get("spec") or {}

            # Find emptyDir volume names
            emptydir_names = set()
            for v in pod_spec.get("volumes") or []:
                if "emptyDir" in v:
                    emptydir_names.add(v.get("name", ""))
            if not emptydir_names:
                continue

            # Map: vol_name -> {compose_svc_name: mount_path}
            vol_mounts = {}

            # Main container (containers[0])
            containers = pod_spec.get("containers") or []
            if containers:
                for vm in containers[0].get("volumeMounts") or []:
                    if vm.get("name", "") in emptydir_names:
                        vol_mounts.setdefault(vm["name"], {})[name] = vm.get("mountPath", "")

            # Init containers
            for ic in pod_spec.get("initContainers") or []:
                ic_name = ic.get("name", "init")
                svc_name = f"{name}-init-{ic_name}"
                for vm in ic.get("volumeMounts") or []:
                    if vm.get("name", "") in emptydir_names:
                        vol_mounts.setdefault(vm["name"], {})[svc_name] = vm.get("mountPath", "")

            # Sidecar containers (containers[1:] — convention shared with workloads.py)
            for sc in containers[1:]:
                sc_name = sc.get("name", "sidecar")
                svc_name = f"{name}-sidecar-{sc_name}"
                for vm in sc.get("volumeMounts") or []:
                    if vm.get("name", "") in emptydir_names:
                        vol_mounts.setdefault(vm["name"], {})[svc_name] = vm.get("mountPath", "")

            # Keep only shared (2+ containers)
            shared = {vn: mounts for vn, mounts in vol_mounts.items() if len(mounts) >= 2}
            if shared:
                result[name] = shared

    return result


class EmptyDirTransform:  # pylint: disable=too-few-public-methods
    """Replace anonymous emptyDir volumes with shared named volumes."""

    name = "emptydir"
    priority = 1000

    def transform(self, compose_services, ingress_entries, ctx):  # pylint: disable=unused-argument
        """Detect shared emptyDirs and wire up named Compose volumes."""
        shared = _find_shared_emptydirs(ctx.manifests)
        if not shared:
            return

        config_volumes = ctx.config.get("volumes") or {}

        for workload_name, vol_map in shared.items():
            for vol_name, svc_mounts in vol_map.items():
                named_vol = f"{workload_name}-{vol_name}"
                any_replaced = False

                for svc_name, mount_path in svc_mounts.items():
                    svc = compose_services.get(svc_name)
                    if not svc:
                        continue

                    volumes = svc.get("volumes") or []
                    new_volumes = []
                    replaced = False
                    for entry in volumes:
                        # Match anonymous emptyDir: bare path, no ":" separator
                        if isinstance(entry, str) and entry == mount_path:
                            new_volumes.append(f"{named_vol}:{mount_path}")
                            replaced = True
                        else:
                            new_volumes.append(entry)

                    if replaced:
                        svc["volumes"] = new_volumes
                        any_replaced = True

                # Declare in compose_extras (user config wins)
                if any_replaced and named_vol not in config_volumes:
                    ctx.compose_extras.setdefault("volumes", {})[named_vol] = {}
                    _emptydir_log(f"{named_vol}: shared between {', '.join(sorted(svc_mounts.keys()))}")
