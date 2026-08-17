import ftplib
import sys
import time

html_path = "/home/rlopez/.gemini/antigravity-ide/brain/370eee4a-f8eb-4d44-9cc3-7be0027fa264/scratch/landing_index.html"

# 1. Read and revert the HTML content
with open(html_path, "r", encoding="utf-8") as f:
    content = f.read()

# Revert header navigation
new_nav = """        <nav class="hidden md:flex items-center gap-8 text-sm font-medium text-gray-400">
          <a href="#trilogy" class="hover:text-cyan-400 transition-colors" data-lang-en="Ecosystem" data-lang-es="Ecosistema">Ecosystem</a>
          <a href="#build-grid" class="hover:text-cyan-400 transition-colors" data-lang-en="Operating Systems" data-lang-es="Sistemas Operativos">Operating Systems</a>
          <a href="#google-credits" class="hover:text-cyan-400 transition-colors" data-lang-en="Google Cloud Justification" data-lang-es="Justificación Google">Google Cloud Justification</a>
          <a href="https://sworn-profusely-alongside.ngrok-free.dev/staging-web/" target="_blank" class="px-3 py-1 bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 rounded-lg hover:bg-cyan-500/20 transition-all font-semibold" data-lang-en="Live Showcase" data-lang-es="Showcase en Vivo">Live Showcase</a>
        </nav>"""

old_nav = """        <nav class="hidden md:flex items-center gap-8 text-sm font-medium text-gray-400">
          <a href="#trilogy" class="hover:text-cyan-400 transition-colors" data-lang-en="Ecosystem" data-lang-es="Ecosistema">Ecosystem</a>
          <a href="#build-grid" class="hover:text-cyan-400 transition-colors" data-lang-en="Operating Systems" data-lang-es="Sistemas Operativos">Operating Systems</a>
          <a href="#google-credits" class="hover:text-cyan-400 transition-colors" data-lang-en="Google Cloud Justification" data-lang-es="Justificación Google">Google Cloud Justification</a>
        </nav>"""

if new_nav in content:
    content = content.replace(new_nav, old_nav)
    print("Reverted header navigation.")

# Revert hero buttons
new_buttons = """      <div class="mt-10 flex flex-wrap gap-4">
        <a href="vigilos.html" class="px-6 py-4 bg-gradient-to-r from-cyan-500 to-blue-600 text-black font-bold rounded-xl hover:opacity-90 transition-all flex items-center gap-2 shadow-lg shadow-cyan-500/10 text-sm">
          <span data-lang-en="Explore VigilOS Flagship Agent" data-lang-es="Explorar Agente Insignia VigilOS">Explore VigilOS Flagship Agent</span>
          <i data-lucide="arrow-right" class="w-4 h-4"></i>
        </a>
        <a href="https://sworn-profusely-alongside.ngrok-free.dev/staging-web/" target="_blank" class="px-6 py-4 bg-gradient-to-r from-purple-500 to-indigo-600 text-white font-bold rounded-xl hover:opacity-90 transition-all flex items-center gap-2 shadow-lg shadow-purple-500/10 text-sm">
          <span data-lang-en="Launch Live Showcase" data-lang-es="Iniciar Showcase en Vivo">Launch Live Showcase</span>
          <i data-lucide="external-link" class="w-4 h-4"></i>
        </a>
        <a href="#google-credits" class="px-6 py-4 bg-white/5 border border-white/10 text-white font-medium rounded-xl hover:bg-white/10 transition-all text-sm" data-lang-en="Why Google Cloud Credits" data-lang-es="Por qué Créditos de Google">
          Why Google Cloud Credits
        </a>
      </div>"""

old_buttons = """      <div class="mt-10 flex flex-wrap gap-4">
        <a href="vigilos.html" class="px-6 py-4 bg-gradient-to-r from-cyan-500 to-blue-600 text-black font-bold rounded-xl hover:opacity-90 transition-all flex items-center gap-2 shadow-lg shadow-cyan-500/10 text-sm">
          <span data-lang-en="Explore VigilOS Flagship Agent" data-lang-es="Explorar Agente Insignia VigilOS">Explore VigilOS Flagship Agent</span>
          <i data-lucide="arrow-right" class="w-4 h-4"></i>
        </a>
        <a href="#google-credits" class="px-6 py-4 bg-white/5 border border-white/10 text-white font-medium rounded-xl hover:bg-white/10 transition-all text-sm" data-lang-en="Why Google Cloud Credits" data-lang-es="Por qué Créditos de Google">
          Why Google Cloud Credits
        </a>
      </div>"""

if new_buttons in content:
    content = content.replace(new_buttons, old_buttons)
    print("Reverted hero buttons.")

with open(html_path, "w", encoding="utf-8") as f:
    f.write(content)

# 2. Upload reverted file via FTP
user = "rlopez"
password = "PCD0ct0r2026@@@"

success = False
for attempt in range(1, 4):
    try:
        print(f"Uploading reverted index.html (Attempt {attempt}/3)...")
        ftp = ftplib.FTP("innerchispa.us", timeout=15)
        ftp.login(user, password)
        ftp.cwd("public_html")
        with open(html_path, "rb") as f:
            ftp.storbinary("STOR index.html", f)
        print("SUCCESS! Original unmodified index.html uploaded back to innerchispa.us")
        ftp.quit()
        success = True
        break
    except Exception as e:
        print(f"Failed: {e}")
        time.sleep(5)

if not success:
    sys.exit(1)
