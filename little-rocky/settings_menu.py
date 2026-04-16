from __future__ import annotations

"""
Menu de réglages interactif pour Little Rocky.

Lancement :
    python little_rocky.py --settings
    python settings_menu.py
"""

import json
import os
import sys
from copy import deepcopy
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, FloatPrompt, IntPrompt, Prompt
from rich.table import Table
from rich.text import Text

SETTINGS_FILE = Path(__file__).parent / "settings.json"
ENV_FILE = Path(__file__).parent / ".env"

console = Console()

# ── Valeurs par défaut (miroir de config.py) ──────────────────────────────────

DEFAULTS: dict[str, Any] = {
    "EDGE_THRESHOLD":          0.08,
    "KELLY_FRACTION":          0.15,
    "MAX_BANKROLL_FRACTION":   0.05,
    "MAX_TRADE_USD":           2.00,
    "MAX_MARKET_USD":          4.00,
    "MAX_TOTAL_EXPOSURE":      50.00,
    "MIN_BET_USD":             0.10,
    "SCAN_INTERVAL_SECONDS":   300,
    "MAX_HOURS_TO_RESOLUTION": 48,
    "SLIPPAGE_TOLERANCE":      0.05,
    "GTC_SLIPPAGE":            0.02,
    "CIRCUIT_BREAKER_LOSSES":  12,
    "CIRCUIT_BREAKER_WINDOW":  20,
    "DAILY_LOSS_LIMIT":        0.10,
    "cities": {
        "NYC": {
            "name": "New York City", "lat": 40.7128, "lon": -74.0060, "rmse": 3.5,
            "aliases": ["new york city", "new york", "nyc", "ny"], "enabled": True,
        },
        "CHICAGO": {
            "name": "Chicago", "lat": 41.8781, "lon": -87.6298, "rmse": 3.8,
            "aliases": ["chicago", "chi"], "enabled": True,
        },
        "DALLAS": {
            "name": "Dallas", "lat": 32.7800, "lon": -96.8000, "rmse": 4.0,
            "aliases": ["dallas", "dfw", "dallas-fort worth"], "enabled": True,
        },
        "ATLANTA": {
            "name": "Atlanta", "lat": 33.7490, "lon": -84.3880, "rmse": 3.6,
            "aliases": ["atlanta", "atl"], "enabled": True,
        },
        "MIAMI": {
            "name": "Miami", "lat": 25.7617, "lon": -80.1918, "rmse": 3.2,
            "aliases": ["miami", "mia"], "enabled": True,
        },
    },
}

# ── Helpers d'affichage ───────────────────────────────────────────────────────

def _pct(v: float) -> str:
    return f"{v * 100:.1f}%"


def _usd(v: float) -> str:
    return f"${v:.2f}"


def _header(title: str) -> None:
    console.print()
    console.print(Panel(f"[bold cyan]{title}[/bold cyan]", expand=False))
    console.print()


def _prompt_float(label: str, current: float, min_val: float = 0.0, max_val: float = 1e9) -> float:
    console.print(f"  {label} [dim](actuel: {current})[/dim]")
    while True:
        raw = Prompt.ask(f"  Nouvelle valeur [dim](Entrée = garder)[/dim]", default="")
        if raw == "":
            return current
        try:
            v = float(raw)
            if min_val <= v <= max_val:
                return v
            console.print(f"  [red]Valeur hors plage [{min_val}, {max_val}][/red]")
        except ValueError:
            console.print("  [red]Entrez un nombre décimal valide.[/red]")


def _prompt_int(label: str, current: int, min_val: int = 1, max_val: int = 10_000) -> int:
    console.print(f"  {label} [dim](actuel: {current})[/dim]")
    while True:
        raw = Prompt.ask(f"  Nouvelle valeur [dim](Entrée = garder)[/dim]", default="")
        if raw == "":
            return current
        try:
            v = int(raw)
            if min_val <= v <= max_val:
                return v
            console.print(f"  [red]Valeur hors plage [{min_val}, {max_val}][/red]")
        except ValueError:
            console.print("  [red]Entrez un entier valide.[/red]")


# ── Classe principale ─────────────────────────────────────────────────────────

class SettingsMenu:

    def __init__(self) -> None:
        self.settings: dict[str, Any] = self._load()
        self.modified: bool = False

    # ── I/O ───────────────────────────────────────────────────────────────────

    def _load(self) -> dict[str, Any]:
        base = deepcopy(DEFAULTS)
        if SETTINGS_FILE.exists():
            try:
                user = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
                for k, v in user.items():
                    if k == "cities":
                        base["cities"] = v
                    else:
                        base[k] = v
            except Exception as exc:
                console.print(f"[red]Impossible de lire settings.json : {exc}[/red]")
        return base

    def _save(self) -> None:
        SETTINGS_FILE.write_text(
            json.dumps(self.settings, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        self.modified = False
        console.print(f"\n[bold green]✓ Sauvegardé dans {SETTINGS_FILE.name}[/bold green]")
        console.print("[dim]Redémarrez le bot pour appliquer les changements.[/dim]\n")

    # ── Boucle principale ─────────────────────────────────────────────────────

    def run(self) -> None:
        while True:
            self._show_main_menu()
            choices = ["1", "2", "3", "4", "5", "6", "7", "8", "0", "q"]
            choice = Prompt.ask(
                "[bold]Choix[/bold]",
                choices=choices,
                show_choices=False,
            )

            if choice == "0":
                if self.modified:
                    if Confirm.ask("\nSauvegarder les modifications avant de quitter?", default=True):
                        self._save()
                console.print("[dim]Au revoir.[/dim]")
                break
            elif choice == "q":
                if self.modified:
                    if not Confirm.ask("\n[yellow]Quitter SANS sauvegarder ?[/yellow]", default=False):
                        continue
                console.print("[dim]Annulé — aucun changement sauvegardé.[/dim]")
                break
            elif choice == "1":
                self._menu_trading()
            elif choice == "2":
                self._menu_risk()
            elif choice == "3":
                self._menu_orders()
            elif choice == "4":
                self._menu_timing()
            elif choice == "5":
                self._menu_cities()
            elif choice == "6":
                self._menu_credentials()
            elif choice == "7":
                self._show_all()
            elif choice == "8":
                self._reset_defaults()

    # ── Menu principal ────────────────────────────────────────────────────────

    def _show_main_menu(self) -> None:
        console.print()
        modified_badge = " [yellow](modifié *)[/yellow]" if self.modified else ""
        console.print(
            Panel(
                f"[bold white]Little Rocky — Menu Réglages[/bold white]{modified_badge}",
                subtitle="[dim]settings.json[/dim]",
                border_style="cyan",
            )
        )
        items = [
            ("1", "Paramètres de trading",     "seuil edge, Kelly, taille mise..."),
            ("2", "Gestion des risques",        "circuit-breaker, perte max journalière..."),
            ("3", "Exécution des ordres",       "slippage FOK/GTC..."),
            ("4", "Timing",                     "intervalle scan, fenêtre résolution..."),
            ("5", "Villes surveillées",         "activer/désactiver, ajouter, modifier..."),
            ("6", "Identifiants (.env)",        "clé Polymarket, Telegram..."),
            ("7", "Afficher tous les réglages", ""),
            ("8", "Réinitialiser aux défauts",  "[red]remet tout à zéro[/red]"),
            ("0", "Sauvegarder et quitter",     ""),
            ("q", "Quitter sans sauvegarder",   ""),
        ]
        for key, label, hint in items:
            hint_str = f"  [dim]{hint}[/dim]" if hint else ""
            console.print(f"  [bold cyan][{key}][/bold cyan] {label}{hint_str}")
        console.print()

    # ── 1. Paramètres de trading ──────────────────────────────────────────────

    def _menu_trading(self) -> None:
        _header("Paramètres de trading")
        s = self.settings

        tbl = Table(show_header=True, header_style="bold magenta", show_lines=False)
        tbl.add_column("Paramètre", style="cyan")
        tbl.add_column("Valeur actuelle", justify="right")
        tbl.add_column("Description")
        tbl.add_row("EDGE_THRESHOLD",        _pct(s["EDGE_THRESHOLD"]),      "Edge minimum pour trader")
        tbl.add_row("KELLY_FRACTION",        _pct(s["KELLY_FRACTION"]),      "Fraction Kelly (mise)")
        tbl.add_row("MAX_BANKROLL_FRACTION", _pct(s["MAX_BANKROLL_FRACTION"]),"Cap bankroll par trade")
        tbl.add_row("MAX_TRADE_USD",         _usd(s["MAX_TRADE_USD"]),       "Cap USD par trade")
        tbl.add_row("MAX_MARKET_USD",        _usd(s["MAX_MARKET_USD"]),      "Cap USD par marché")
        tbl.add_row("MAX_TOTAL_EXPOSURE",    _usd(s["MAX_TOTAL_EXPOSURE"]),  "Exposition totale max")
        tbl.add_row("MIN_BET_USD",           _usd(s["MIN_BET_USD"]),         "Mise minimum (sinon ignorée)")
        console.print(tbl)
        console.print("[dim]Appuyez Entrée pour garder la valeur actuelle.[/dim]\n")

        changed = False

        v = _prompt_float("EDGE_THRESHOLD — edge minimum (%)", s["EDGE_THRESHOLD"], 0.01, 0.99)
        if v != s["EDGE_THRESHOLD"]: s["EDGE_THRESHOLD"] = v; changed = True

        v = _prompt_float("KELLY_FRACTION — fraction Kelly (%)", s["KELLY_FRACTION"], 0.01, 1.0)
        if v != s["KELLY_FRACTION"]: s["KELLY_FRACTION"] = v; changed = True

        v = _prompt_float("MAX_BANKROLL_FRACTION — cap bankroll/trade (%)", s["MAX_BANKROLL_FRACTION"], 0.001, 0.5)
        if v != s["MAX_BANKROLL_FRACTION"]: s["MAX_BANKROLL_FRACTION"] = v; changed = True

        v = _prompt_float("MAX_TRADE_USD — cap USD par trade", s["MAX_TRADE_USD"], 0.10, 10_000.0)
        if v != s["MAX_TRADE_USD"]: s["MAX_TRADE_USD"] = v; changed = True

        v = _prompt_float("MAX_MARKET_USD — cap USD par marché", s["MAX_MARKET_USD"], 0.10, 10_000.0)
        if v != s["MAX_MARKET_USD"]: s["MAX_MARKET_USD"] = v; changed = True

        v = _prompt_float("MAX_TOTAL_EXPOSURE — exposition totale max ($)", s["MAX_TOTAL_EXPOSURE"], 1.0, 1_000_000.0)
        if v != s["MAX_TOTAL_EXPOSURE"]: s["MAX_TOTAL_EXPOSURE"] = v; changed = True

        v = _prompt_float("MIN_BET_USD — mise minimum ($)", s["MIN_BET_USD"], 0.01, 100.0)
        if v != s["MIN_BET_USD"]: s["MIN_BET_USD"] = v; changed = True

        if changed:
            self.modified = True
            console.print("\n[green]✓ Paramètres de trading mis à jour.[/green]")

    # ── 2. Gestion des risques ────────────────────────────────────────────────

    def _menu_risk(self) -> None:
        _header("Gestion des risques")
        s = self.settings

        tbl = Table(show_header=True, header_style="bold magenta", show_lines=False)
        tbl.add_column("Paramètre", style="cyan")
        tbl.add_column("Valeur actuelle", justify="right")
        tbl.add_column("Description")
        tbl.add_row("CIRCUIT_BREAKER_LOSSES", str(s["CIRCUIT_BREAKER_LOSSES"]), "Nb pertes → coupe circuit")
        tbl.add_row("CIRCUIT_BREAKER_WINDOW", str(s["CIRCUIT_BREAKER_WINDOW"]), "Fenêtre glissante (nb trades)")
        tbl.add_row("DAILY_LOSS_LIMIT",       _pct(s["DAILY_LOSS_LIMIT"]),      "Perte journalière max (% bankroll)")
        console.print(tbl)
        console.print("[dim]Appuyez Entrée pour garder la valeur actuelle.[/dim]\n")

        changed = False

        v = _prompt_int("CIRCUIT_BREAKER_LOSSES — nb pertes max", s["CIRCUIT_BREAKER_LOSSES"], 1, 100)
        if v != s["CIRCUIT_BREAKER_LOSSES"]: s["CIRCUIT_BREAKER_LOSSES"] = v; changed = True

        v = _prompt_int("CIRCUIT_BREAKER_WINDOW — fenêtre glissante", s["CIRCUIT_BREAKER_WINDOW"], 2, 200)
        if v != s["CIRCUIT_BREAKER_WINDOW"]: s["CIRCUIT_BREAKER_WINDOW"] = v; changed = True

        v = _prompt_float("DAILY_LOSS_LIMIT — perte journalière max (%)", s["DAILY_LOSS_LIMIT"], 0.01, 1.0)
        if v != s["DAILY_LOSS_LIMIT"]: s["DAILY_LOSS_LIMIT"] = v; changed = True

        if changed:
            self.modified = True
            console.print("\n[green]✓ Paramètres de risque mis à jour.[/green]")

    # ── 3. Exécution des ordres ───────────────────────────────────────────────

    def _menu_orders(self) -> None:
        _header("Exécution des ordres")
        s = self.settings

        tbl = Table(show_header=True, header_style="bold magenta", show_lines=False)
        tbl.add_column("Paramètre", style="cyan")
        tbl.add_column("Valeur actuelle", justify="right")
        tbl.add_column("Description")
        tbl.add_row("SLIPPAGE_TOLERANCE", _pct(s["SLIPPAGE_TOLERANCE"]), "Slippage max pour ordres FOK")
        tbl.add_row("GTC_SLIPPAGE",       _pct(s["GTC_SLIPPAGE"]),       "Slippage pour ordres GTC (fallback)")
        console.print(tbl)
        console.print("[dim]Appuyez Entrée pour garder la valeur actuelle.[/dim]\n")

        changed = False

        v = _prompt_float("SLIPPAGE_TOLERANCE — slippage FOK (%)", s["SLIPPAGE_TOLERANCE"], 0.001, 0.5)
        if v != s["SLIPPAGE_TOLERANCE"]: s["SLIPPAGE_TOLERANCE"] = v; changed = True

        v = _prompt_float("GTC_SLIPPAGE — slippage GTC (%)", s["GTC_SLIPPAGE"], 0.001, 0.5)
        if v != s["GTC_SLIPPAGE"]: s["GTC_SLIPPAGE"] = v; changed = True

        if changed:
            self.modified = True
            console.print("\n[green]✓ Paramètres d'exécution mis à jour.[/green]")

    # ── 4. Timing ─────────────────────────────────────────────────────────────

    def _menu_timing(self) -> None:
        _header("Timing")
        s = self.settings

        tbl = Table(show_header=True, header_style="bold magenta", show_lines=False)
        tbl.add_column("Paramètre", style="cyan")
        tbl.add_column("Valeur actuelle", justify="right")
        tbl.add_column("Description")
        tbl.add_row("SCAN_INTERVAL_SECONDS",   f"{s['SCAN_INTERVAL_SECONDS']}s",   "Intervalle entre cycles (secondes)")
        tbl.add_row("MAX_HOURS_TO_RESOLUTION", f"{s['MAX_HOURS_TO_RESOLUTION']}h", "Fenêtre max avant résolution (heures)")
        console.print(tbl)
        console.print("[dim]Appuyez Entrée pour garder la valeur actuelle.[/dim]\n")

        changed = False

        v = _prompt_int("SCAN_INTERVAL_SECONDS — intervalle (s)", s["SCAN_INTERVAL_SECONDS"], 30, 86400)
        if v != s["SCAN_INTERVAL_SECONDS"]: s["SCAN_INTERVAL_SECONDS"] = v; changed = True

        v = _prompt_int("MAX_HOURS_TO_RESOLUTION — fenêtre résolution (h)", s["MAX_HOURS_TO_RESOLUTION"], 1, 720)
        if v != s["MAX_HOURS_TO_RESOLUTION"]: s["MAX_HOURS_TO_RESOLUTION"] = v; changed = True

        if changed:
            self.modified = True
            console.print("\n[green]✓ Paramètres de timing mis à jour.[/green]")

    # ── 5. Villes surveillées ─────────────────────────────────────────────────

    def _menu_cities(self) -> None:
        while True:
            _header("Villes surveillées")
            cities = self.settings["cities"]

            tbl = Table(show_header=True, header_style="bold magenta", show_lines=True)
            tbl.add_column("#",       style="dim",  width=3)
            tbl.add_column("Clé",     style="cyan", no_wrap=True)
            tbl.add_column("Nom",     no_wrap=True)
            tbl.add_column("Lat",     justify="right")
            tbl.add_column("Lon",     justify="right")
            tbl.add_column("RMSE",    justify="right")
            tbl.add_column("Statut",  justify="center")

            keys = list(cities.keys())
            for i, key in enumerate(keys, 1):
                c = cities[key]
                enabled = c.get("enabled", True)
                status = "[green]ON[/green]" if enabled else "[red]OFF[/red]"
                tbl.add_row(str(i), key, c["name"], str(c["lat"]), str(c["lon"]), str(c["rmse"]), status)
            console.print(tbl)

            console.print(
                "  [cyan][t][/cyan] Activer/désactiver une ville  "
                "[cyan][m][/cyan] Modifier une ville  "
                "[cyan][a][/cyan] Ajouter une ville  "
                "[cyan][s][/cyan] Supprimer une ville  "
                "[cyan][r][/cyan] Retour"
            )
            console.print()
            action = Prompt.ask("Action", choices=["t", "m", "a", "s", "r"], default="r")

            if action == "r":
                break

            elif action == "t":
                key = Prompt.ask("Clé de la ville (ex: NYC)").strip().upper()
                if key not in cities:
                    console.print(f"[red]Ville '{key}' introuvable.[/red]")
                    continue
                cities[key]["enabled"] = not cities[key].get("enabled", True)
                state = "activée" if cities[key]["enabled"] else "désactivée"
                console.print(f"[green]{key} {state}.[/green]")
                self.modified = True

            elif action == "m":
                key = Prompt.ask("Clé de la ville à modifier").strip().upper()
                if key not in cities:
                    console.print(f"[red]Ville '{key}' introuvable.[/red]")
                    continue
                c = cities[key]
                c["name"] = Prompt.ask(f"  Nom complet", default=c["name"])
                c["lat"]  = float(Prompt.ask(f"  Latitude",  default=str(c["lat"])))
                c["lon"]  = float(Prompt.ask(f"  Longitude", default=str(c["lon"])))
                c["rmse"] = float(Prompt.ask(f"  RMSE (°F)", default=str(c["rmse"])))
                aliases_str = Prompt.ask(
                    f"  Alias (séparés par virgule)",
                    default=", ".join(c.get("aliases", [])),
                )
                c["aliases"] = [a.strip().lower() for a in aliases_str.split(",") if a.strip()]
                self.modified = True
                console.print(f"[green]{key} mis à jour.[/green]")

            elif action == "a":
                key = Prompt.ask("Nouvelle clé (ex: LOS_ANGELES)").strip().upper()
                if key in cities:
                    console.print(f"[red]'{key}' existe déjà.[/red]")
                    continue
                name  = Prompt.ask("  Nom complet")
                lat   = float(Prompt.ask("  Latitude"))
                lon   = float(Prompt.ask("  Longitude"))
                rmse  = float(Prompt.ask("  RMSE historique (°F)", default="4.0"))
                aliases_str = Prompt.ask("  Alias (séparés par virgule)", default=key.lower())
                aliases = [a.strip().lower() for a in aliases_str.split(",") if a.strip()]
                cities[key] = {
                    "name": name, "lat": lat, "lon": lon,
                    "rmse": rmse, "aliases": aliases, "enabled": True,
                }
                self.modified = True
                console.print(f"[green]{key} ajoutée.[/green]")

            elif action == "s":
                key = Prompt.ask("Clé à supprimer").strip().upper()
                if key not in cities:
                    console.print(f"[red]'{key}' introuvable.[/red]")
                    continue
                if Confirm.ask(f"[red]Supprimer définitivement {key} ?[/red]", default=False):
                    del cities[key]
                    self.modified = True
                    console.print(f"[green]{key} supprimée.[/green]")

    # ── 6. Identifiants (.env) ────────────────────────────────────────────────

    def _menu_credentials(self) -> None:
        _header("Identifiants (.env)")

        env_vars = {
            "POLYMARKET_PRIVATE_KEY":  ("Clé privée Polymarket",    True),
            "POLYMARKET_SAFE_ADDRESS": ("Adresse Safe Polymarket",   False),
            "TELEGRAM_BOT_TOKEN":      ("Token bot Telegram",        True),
            "TELEGRAM_CHAT_ID":        ("Chat ID Telegram",          False),
        }

        current: dict[str, str] = {}
        if ENV_FILE.exists():
            for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, _, v = line.partition("=")
                    current[k.strip()] = v.strip()

        tbl = Table(show_header=True, header_style="bold magenta", show_lines=False)
        tbl.add_column("Variable", style="cyan", no_wrap=True)
        tbl.add_column("Description")
        tbl.add_column("Configuré ?", justify="center")

        for var, (desc, _) in env_vars.items():
            val = current.get(var, "")
            configured = "[green]✓[/green]" if val else "[red]✗[/red]"
            tbl.add_row(var, desc, configured)
        console.print(tbl)
        console.print()

        if not Confirm.ask("Modifier les identifiants ?", default=False):
            return

        updated: dict[str, str] = dict(current)
        for var, (desc, sensitive) in env_vars.items():
            existing = current.get(var, "")
            masked = ("*" * min(8, len(existing))) if sensitive and existing else existing
            display = f"[dim](actuel: {masked or 'non défini'})[/dim]"
            console.print(f"\n  {desc} {display}")
            val = Prompt.ask(f"  {var} [dim](Entrée = garder)[/dim]", default="", password=sensitive)
            if val:
                updated[var] = val
            elif existing:
                updated[var] = existing

        # Écrire le fichier .env
        lines = []
        for var in env_vars:
            v = updated.get(var, "")
            lines.append(f"{var}={v}")

        # Garder les variables inconnues
        for k, v in current.items():
            if k not in env_vars:
                lines.append(f"{k}={v}")

        ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
        console.print(f"\n[green]✓ {ENV_FILE.name} mis à jour.[/green]")

    # ── 7. Afficher tous les réglages ─────────────────────────────────────────

    def _show_all(self) -> None:
        _header("Tous les réglages actuels")
        s = self.settings

        sections = [
            ("Trading", [
                ("EDGE_THRESHOLD",        _pct(s["EDGE_THRESHOLD"])),
                ("KELLY_FRACTION",        _pct(s["KELLY_FRACTION"])),
                ("MAX_BANKROLL_FRACTION", _pct(s["MAX_BANKROLL_FRACTION"])),
                ("MAX_TRADE_USD",         _usd(s["MAX_TRADE_USD"])),
                ("MAX_MARKET_USD",        _usd(s["MAX_MARKET_USD"])),
                ("MAX_TOTAL_EXPOSURE",    _usd(s["MAX_TOTAL_EXPOSURE"])),
                ("MIN_BET_USD",           _usd(s["MIN_BET_USD"])),
            ]),
            ("Risques", [
                ("CIRCUIT_BREAKER_LOSSES", str(s["CIRCUIT_BREAKER_LOSSES"])),
                ("CIRCUIT_BREAKER_WINDOW", str(s["CIRCUIT_BREAKER_WINDOW"])),
                ("DAILY_LOSS_LIMIT",       _pct(s["DAILY_LOSS_LIMIT"])),
            ]),
            ("Ordres", [
                ("SLIPPAGE_TOLERANCE", _pct(s["SLIPPAGE_TOLERANCE"])),
                ("GTC_SLIPPAGE",       _pct(s["GTC_SLIPPAGE"])),
            ]),
            ("Timing", [
                ("SCAN_INTERVAL_SECONDS",   f"{s['SCAN_INTERVAL_SECONDS']}s"),
                ("MAX_HOURS_TO_RESOLUTION", f"{s['MAX_HOURS_TO_RESOLUTION']}h"),
            ]),
        ]

        for section_name, rows in sections:
            tbl = Table(title=section_name, show_header=False, show_lines=False, box=None)
            tbl.add_column("Paramètre", style="cyan", min_width=28)
            tbl.add_column("Valeur", justify="right", style="bold white")
            for k, v in rows:
                tbl.add_row(k, v)
            console.print(tbl)
            console.print()

        # Villes
        tbl = Table(title="Villes", show_header=True, header_style="bold magenta", show_lines=False)
        tbl.add_column("Clé",  style="cyan")
        tbl.add_column("Nom")
        tbl.add_column("Lat",  justify="right")
        tbl.add_column("Lon",  justify="right")
        tbl.add_column("RMSE", justify="right")
        tbl.add_column("ON",   justify="center")
        for key, c in s["cities"].items():
            on = "[green]✓[/green]" if c.get("enabled", True) else "[red]✗[/red]"
            tbl.add_row(key, c["name"], str(c["lat"]), str(c["lon"]), str(c["rmse"]), on)
        console.print(tbl)

        Prompt.ask("\n[dim]Appuyez Entrée pour continuer[/dim]", default="")

    # ── 8. Réinitialiser ──────────────────────────────────────────────────────

    def _reset_defaults(self) -> None:
        console.print()
        if Confirm.ask(
            "[bold red]Réinitialiser TOUS les paramètres aux valeurs par défaut ?[/bold red]",
            default=False,
        ):
            self.settings = deepcopy(DEFAULTS)
            self.modified = True
            console.print("[yellow]Paramètres réinitialisés. Sauvegardez pour appliquer.[/yellow]")


# ── Point d'entrée ────────────────────────────────────────────────────────────

def run_settings_menu() -> None:
    SettingsMenu().run()


if __name__ == "__main__":
    run_settings_menu()
