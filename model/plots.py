"""Optional plots (matplotlib). The model does not depend on them."""
import os, csv
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def make_plots():
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except Exception as e:
        return {"available": False, "reason": str(e)}
    R = os.path.join(ROOT, "results")
    def read(name):
        with open(os.path.join(R,name), newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))
    tp = read("equilibrium_map.csv")
    fig, ax = plt.subplots(1,2, figsize=(11,4))
    for p in ("1.0","5.0","10.0","20.0","25.0","30.0","40.0"):
        rows = [r for r in tp if r["p_bar"]==p]
        ax[0].plot([float(r["T_K"]) for r in rows], [float(r["X_CH4"]) for r in rows], label=f"{p} bar")
        ax[1].plot([float(r["T_K"]) for r in rows], [float(r["H2_CO"]) for r in rows], label=f"{p} bar")
    ax[0].set_xlabel("T, K"); ax[0].set_ylabel("CH4 conversion"); ax[0].legend(fontsize=7); ax[0].grid(alpha=.3)
    ax[1].set_xlabel("T, K"); ax[1].set_ylabel("H2/CO (dry)"); ax[1].grid(alpha=.3)
    fig.suptitle("L0 SMR equilibrium (S/C=3, NIST-JANAF thermo, ideal gas)")
    fig.tight_layout(); fig.savefig(os.path.join(R,"equilibrium_map.png"), dpi=130); plt.close(fig)
    sc = read("sc_sweep.csv")
    fig, ax = plt.subplots(figsize=(6,4))
    ax.plot([float(r["SC"]) for r in sc], [float(r["C_affinity_kJ_mol"]) for r in sc], label="carbon affinity")
    ax.axhline(0, color="r", ls="--", label="graphite stability limit")
    ax.set_xlabel("S/C, mol/mol hydrocarbon C"); ax.set_ylabel("Delta_mu_C, kJ/mol")
    ax.set_title("1123.15 K, 25 bar(a): graphite stability boundary"); ax.grid(alpha=.3); ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(R,"carbon_boundary.png"), dpi=130); plt.close(fig)
    co2 = read("co2_sweep.csv")
    fig, ax = plt.subplots(figsize=(6,4))
    ax.plot([float(r["CO2_C"]) for r in co2], [float(r["SN"]) for r in co2], label="SN")
    ax.axhline(2.0, color="g", ls="--", label="methanol target SN=2")
    ax.set_xlabel("imported CO2/C, mol/mol"); ax.set_ylabel("stoichiometric number SN")
    ax.set_title("Tuning syngas by CO2 import"); ax.grid(alpha=.3); ax.legend()
    fig.tight_layout(); fig.savefig(os.path.join(R,"sn_tuning.png"), dpi=130); plt.close(fig)
    return {"available": True, "files": ["equilibrium_map.png","carbon_boundary.png","sn_tuning.png"]}
