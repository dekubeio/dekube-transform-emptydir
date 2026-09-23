"""emptydir — dekube transform.

Auto-detects emptyDir volumes shared between init/sidecar/main containers
of the same pod and replaces anonymous Compose volumes with shared named
volumes. Runs early (priority 1000) so downstream transforms see the
corrected volume entries.
"""

from dekube import iter_workloads, iter_named_containers, log  # pylint: disable=import-error


class EmptyDirTransform:  # pylint: disable=too-few-public-methods
    """Replace anonymous emptyDir volumes with shared named volumes."""

    name = "emptydir"
    priority = 1000

    @staticmethod
    def _find_shared_emptydirs(manifests):
        """Scan workload manifests for emptyDir volumes mounted by 2+ containers.

        Returns: {workload_name: {vol_name: {compose_svc_name: mount_path}}}
        """
        result = {}
        for name, pod_spec in iter_workloads(manifests):
            emptydir_names = {
                v.get("name", "") for v in pod_spec.get("volumes") or [] if v and "emptyDir" in v
            }
            if not emptydir_names:
                continue

            # Map: vol_name -> {compose_svc_name: mount_path}
            vol_mounts = {}
            for svc_name, container in iter_named_containers(name, pod_spec):
                for vm in container.get("volumeMounts") or []:
                    if not vm:
                        continue
                    if vm.get("name", "") in emptydir_names:
                        vol_mounts.setdefault(vm["name"], {})[svc_name] = vm.get("mountPath", "")

            # Keep only shared (2+ containers)
            shared = {vn: mounts for vn, mounts in vol_mounts.items() if len(mounts) >= 2}
            if shared:
                result[name] = shared

        return result

    def transform(self, compose_services, ingress_entries, ctx):  # pylint: disable=unused-argument
        """Detect shared emptyDirs and wire up named Compose volumes."""
        shared = self._find_shared_emptydirs(ctx.manifests)
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
                    log(self.name, f"{named_vol}: shared between {', '.join(sorted(svc_mounts.keys()))}")
