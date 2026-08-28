# Publicar PRIVACY.md en GitHub (LinkedIn Developer)

LinkedIn pide una **URL pública HTTPS** de Privacy Policy al crear la app.

---

## Opción recomendada — repo pequeño solo legal

Ya preparado en el servidor:

```
/home/rlopez/projects/innerchispa-linkedin-privacy/
├── PRIVACY.md
└── README.md
```

### Comandos (copiar/pegar en terminal del servidor)

```bash
cd /home/rlopez/projects/innerchispa-linkedin-privacy
git init
git add PRIVACY.md README.md
git commit -m "Add privacy policy for LinkedIn Developer app"
gh repo create innerchispa-linkedin-privacy --public --source=. --remote=origin --push \
  --description "Privacy policy — InnerChispa LinkedIn automation"
```

### URL para LinkedIn Developer Portal

Pega esta en **Privacy policy URL**:

```
https://github.com/Rafa-Innerchispa/innerchispa-linkedin-privacy/blob/main/PRIVACY.md
```

(Si la rama se llama `master`, cambia `main` → `master`.)

LinkedIn acepta enlaces `github.com/.../blob/...` — no hace falta web aparte.

---

## Opción B — dentro de raphiia-openai

También está `PRIVACY.md` en la raíz de `raphiia-openai`. Si creas ese repo:

```
https://github.com/Rafa-Innerchispa/raphiia-openai/blob/main/PRIVACY.md
```

Mejor repo **dedicado** (opción A) si el código MCP sigue privado.

---

## Opción C — GitHub Pages (URL más “web”)

Si prefieres `https://Rafa-Innerchispa.github.io/...`:

1. Repo público con carpeta `docs/`
2. GitHub → Settings → Pages → Branch `main`, folder `/docs`
3. `docs/index.html` redirige a PRIVACY o renderiza el texto

Para LinkedIn **no es obligatorio** — el enlace blob de GitHub basta.

---

## Campos LinkedIn Developer (referencia)

| Campo | Valor sugerido |
|-------|----------------|
| **Privacy policy URL** | URL de arriba |
| **App name** | InnerSpark LinkedIn Automation |
| **Logo** | logo InnerChispa/PC Doctor |
| **Redirect URLs** | tu callback OAuth (localhost o ngrok en pruebas) |

---

## Actualizar la política

1. Edita `PRIVACY.md`
2. `git add PRIVACY.md && git commit -m "Update privacy policy" && git push`
3. La URL en LinkedIn **no cambia** — mismo enlace.
