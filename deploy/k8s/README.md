# Kubernetes — szkielet (placeholder)

Cloud-agnostyczny, minimalny szkielet do wdrożenia kontenera `legacy-documenter`.
To **punkt startowy**, nie produkcyjna konfiguracja — patrz uwagi niżej.

## Pliki

| Plik | Rola |
|---|---|
| `namespace.yaml` | namespace `legacy-documenter` |
| `configmap.yaml` | konfiguracja jawna (provider, base URL, nazwy modeli, REPO_PATH) |
| `secret.example.yaml` | **przykład** sekretu — nie commituj realnych kluczy |
| `deployment.yaml` | 1 replika, probes na `/_stcore/health`, cache indeksu |
| `service.yaml` | ClusterIP :80 → :8501 |
| `ingress.yaml` | wejście HTTP (podmień host + kontroler) |
| `kustomization.yaml` | spina całość (`kubectl apply -k`) |

## Wdrożenie

```bash
# 1. Zbuduj i wypchnij obraz do swojego rejestru (np. Azure ACR)
podman build -t myregistry.azurecr.io/legacy-documenter:1.0.0 -f Containerfile .
podman push myregistry.azurecr.io/legacy-documenter:1.0.0
#    → ustaw ten obraz w deployment.yaml lub przez kustomization (images:)

# 2. Sekrety (NIE z pliku w gicie)
kubectl create namespace legacy-documenter
kubectl create secret generic legacy-documenter-secrets \
  --namespace legacy-documenter \
  --from-literal=AZURE_ANTHROPIC_API_KEY=... \
  --from-literal=AZURE_OPENAI_API_KEY=...

# 3. Reszta zasobów
kubectl apply -k deploy/k8s

# 4. Lokalny podgląd
kubectl -n legacy-documenter port-forward svc/legacy-documenter 8501:80
```

## Podman → k8s (alternatywa)

Podman potrafi wygenerować i odtworzyć manifesty bez klastra:

```bash
podman kube generate legacy-documenter -f legacy-documenter-pod.yaml
podman kube play legacy-documenter-pod.yaml
```

## Uwagi (zanim to pójdzie na produkcję)

- **Stan / skalowanie:** Streamlit trzyma stan sesji w pamięci procesu. `replicas > 1`
  wymaga sticky sessions na Ingressie albo wyniesienia stanu (historia czatów) na zewnątrz.
- **Sekrety:** użyj Azure Key Vault (CSI driver) / sealed-secrets / External Secrets — nie `Secret` w repo.
- **Repo docelowe i sandbox:** `git_commit`/`apply_edit` wymagają zapisywalnego repo z `.git`.
  W demo repo jest w obrazie; do realnego użycia zamontuj repo użytkownika jako PVC i ustaw `REPO_PATH`.
- **Trwałość indeksu:** `emptyDir` jest ulotny — podmień na PVC, by indeks przeżył restart.
- **Azure:** na AKS dodaj AGIC/managed ingress + ACR pull secret; alternatywa bez klastra to Azure Container Apps (ten sam obraz).
