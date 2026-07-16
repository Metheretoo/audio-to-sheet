import win32com.client

wmi = win32com.client.GetObject('winmgmts:')

# Chercher les classes de température GPU
classes_to_check = [
    'MSFT_GPUThermal',
    'MSFT_GPUControllerStats', 
    'WmiApSensor',
    'MSAcpi_ThermalZoneTemperature',
    'IntelHwMon',
    'IntelGPUThermal',
    'MSFT_GPUComputeSummary',
    'MSFT_GpuDesc',
    'WmiPerfInstance',
]

print("=== Vérification des classes WMI GPU ===")
for c in classes_to_check:
    try:
        instances = wmi.InstancesOf(c)
        print(f"\n{c}: {len(instances)} instances")
        for i in instances:
            props = {}
            try:
                for prop in i.Properties_:
                    try:
                        props[prop.Name] = prop.Value
                    except:
                        pass
            except:
                pass
            print(f"  Properties: {list(props.keys())[:20]}")
    except Exception as e:
        print(f"{c}: ERREUR - {str(e)[:100]}")

# Vérifier aussi root\root\wmi
print("\n=== Classes WMI root\wmi contenant 'GPU' ou 'Temp' ===")
try:
    wmi_wmi = win32com.client.GetObject('winmgmts:\\root\wmi')
    gpu_classes = ['MSAcpi_ThermalZoneTemperature', 'WmiHwSensor', 'GpuSensorData', 
                   'GpuThermalSensor', 'IntelGpuThermal', 'IntelHwMonSensor']
    for c in gpu_classes:
        try:
            instances = wmi_wmi.InstancesOf(c)
            print(f"\n{c}: {len(instances)} instances")
            for i in instances:
                # Afficher les propriétés pertinentes
                sensors = {}
                for prop in i.Properties_:
                    try:
                        val = prop.Value
                        if val is not None and isinstance(val, (int, float, str, bool)):
                            sensors[prop.Name] = val
                    except:
                        pass
                if sensors:
                    print(f"  {sensors}")
        except Exception as e:
            print(f"{c}: ERREUR - {str(e)[:80]}")
except Exception as e:
    print(f"Erreur root\wmi: {e}")

# Vérifier WmiHwSensor (classe standard Windows pour les capteurs matériels)
print("\n=== WmiHwSensor détaillé ===")
try:
    wmi_wmi = win32com.client.GetObject('winmgmts:\\root\wmi')
    sensors = wmi_wmi.InstancesOf('WmiHwSensor')
    print(f"Nombre de capteurs: {len(sensors)}")
    for s in sensors:
        try:
            name = s.SensorName if hasattr(s, 'SensorName') else 'N/A'
            current = s.CurrentValue if hasattr(s, 'CurrentValue') else 'N/A'
            unit = s.SensorType if hasattr(s, 'SensorType') else 'N/A'
            # Vérifier si c'est un capteur de température
            if hasattr(s, 'MinimumValue') and hasattr(s, 'MaximumValue'):
                print(f"  Nom: {name}, Valeur: {current}, Type: {unit}")
        except:
            pass
except Exception as e:
    print(f"Erreur WmiHwSensor: {e}")