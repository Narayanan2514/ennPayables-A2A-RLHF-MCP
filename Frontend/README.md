# ennPayables (EBS) — Frontend

Standalone React/Vite frontend for the ennPayables Oracle EBS invoice module,
extracted from the main ennVault Frontend. See `../README.md` for how this
fits together with the backend.

## Run

```sh
npm install
npm run dev       # http://localhost:8090
```

The app talks to the ennPayables EBS backend at `http://localhost:8011`
(see `ennPayables/backend`). Update the `API_URL` constants in
`src/pages/ennPayables/EBS/*.tsx` and `src/pages/Login.tsx` if the backend
runs on a different host/port.
