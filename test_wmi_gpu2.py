import win32com.client

# Chercher les classes GPU dans root\cimv2
wmi = win32com.client.GetObject('winmgmts:\\root\cimv2')

# Chercher les classes liées au GPU
gpu_related = []
for class_name in dir(wmi):
    if 'gpu' in class_name.lower() or 'video' in class_name.lower() or 'display' in class_name.lower():
        gpu_related.append(class_name)

print("=== Classes liées au GPU dans root\cimv2 ===")
print(f"Total: {len(gpu_related)} classes")
for c in sorted(set(gpu_related))[:30]:
    print(f"  {c}")

# Vérifier Win32_VideoController en détail
print("\n=== Win32_VideoController détaillé ===")
try:
    controllers = wmi.InstancesOf('Win32_VideoController')
    print(f"Nombre de contrôleurs: {len(controllers)}")
    for ctrl in controllers:
        print(f"\n  Nom: {ctrl.Name}")
        print(f"  DriverVersion: {ctrl.DriverVersion}")
        print(f"  VideoProcessor: {ctrl.VideoProcessor}")
        print(f"  DedicatedMemory: {ctrl.DedicatedMemory}")
        print(f"  SharedMemory: {ctrl.SharedMemory}")
        # Vérifier les propriétés de température
        props = []
        for prop in ctrl.Properties_:
            try:
                val = prop.Value
                if val is not None and isinstance(val, (int, float, str, bool)) and 'temp' in str(prop.Name).lower():
                    props.append((prop.Name, val))
            except:
                pass
        if props:
            print(f"  Propriétés température: {props}")
except Exception as e:
    print(f"Erreur: {e}")

# Vérifier Win32_PerfFormattedData par GPU
print("\n=== Win32_PerfFormattedData GPU ===")
perf_classes = [
    'Win32_PerfFormattedData_DxGpukmd_DxGpukmd',
    'Win32_PerfFormattedData_GpuPerfSvc_GpuPerfSvc',
    'Win32_PerfFormattedData_IntelGpuIo_IntelGpuIo',
    'Win32_PerfFormattedData_IntelGpuEng_IntelGpuEng',
    'Win32_PerfFormattedData_GPUEngine',
    'Win32_PerfFormattedData_GpuMemory',
]
for c in perf_classes:
    try:
        instances = wmi.InstancesOf(c)
        print(f"\n{c}: {len(instances)} instances")
        if len(instances) > 0:
            # Afficher les propriétés de la première instance
            props = {}
            for prop in instances[0].Properties_:
                try:
                    val = prop.Value
                    if val is not None and isinstance(val, (int, float, str, bool)):
                        props[prop.Name] = val
                except:
                    pass
            print(f"  Properties: {list(props.keys())[:30]}")
    except Exception as e:
        print(f"{c}: ERREUR - {str(e)[:80]}")

# Vérifier les classes Intel spécifiques
print("\n=== Classes Intel dans root\cimv2 ===")
intel_classes = []
for class_name in ['Win32_PnPEntity', 'Win32_Sensor', 'Win32_SystemEnclosure']:
    try:
        instances = wmi.InstancesOf(class_name)
        # Filtrer pour Intel
        intel_count = 0
        for inst in instances:
            try:
                if 'Intel' in str(inst.Name) + str(inst.Manufacturer) + str(inst.PNPDeviceID):
                    intel_count += 1
                    if intel_count <= 3:
                        print(f"  {class_name}: {inst.Name} ({inst.PNPDeviceID})")
            except:
                pass
        if intel_count > 0:
            print(f"  -> {intel_count} résultats Intel dans {class_name}")
    except Exception as e:
        print(f"{class_name}: ERREUR - {str(e)[:80]}")