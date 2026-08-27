"""
Calculation engine for FPEL Proposal Generator.
Environmental impact + Termination charges (buyout values).
"""

import math

# ── Environmental Constants ──────────────────────────────────
ENV_COAL = 0.47       # kg/kWh
ENV_CO2 = 0.97        # kg/kWh
ENV_SOX = 0.007       # kg/kWh
ENV_NOX = 0.0043      # kg/kWh
ENV_WATER = 2.3       # L/kWh
ENV_CO2_PER_TREE = 48 / 2.20462  # ~21.77 kg/tree/year


def calc_environmental(annual_gen_kwh):
    """Returns dict of environmental impact from annual generation."""
    coal = annual_gen_kwh * ENV_COAL / 1000
    co2 = annual_gen_kwh * ENV_CO2 / 1000
    water = annual_gen_kwh * ENV_WATER
    trees = co2 * 1000 / ENV_CO2_PER_TREE
    return {
        "coal_tons": coal,
        "co2_tons": co2,
        "sox_tons": annual_gen_kwh * ENV_SOX / 1000,
        "nox_tons": annual_gen_kwh * ENV_NOX / 1000,
        "water_litres": water,
        "trees": trees,
    }


# ── Termination Charges (Buyout Values) ─────────────────────
# Fixed assumptions from the model
PR_RATIO = 0.76
DEGRADATION = 0.0067
BAD_DEBTS = 0.02
INSURANCE_RATE = 0.0025
TAX_RATE = 0.15 * 1.12 * 1.04       # ~0.17472
IT_ON_SALE_RATE = 0.34
DEP_IT_ACT = 0.40                    # WDV depreciation rate (IT Act)
ADDITIONAL_DEP = 0.20                # Additional depreciation year 1
OM_ESCALATION = 0.05
LOAN_FRACTION = 0.70
INTEREST_RATE = 0.093
EQUIPMENT_CHANGE_RATE = 0.01         # 1% of total cost after year 10

# O&M base cost lookup (Rs/kWp/annum before 1.18x)
OM_LOOKUP = [
    (250,   400),    # Small: <250 kWp
    (1000,  350),    # Medium: 250–1000 kWp
    (1e9,   250),    # Large: >=1000 kWp
]


def _om_base(capacity_kwp):
    """O&M base cost Rs/kWp/annum = (lookup + 29) * 1.18"""
    for threshold, cost in OM_LOOKUP:
        if capacity_kwp < threshold:
            return (cost + 29) * 1.18
    return (250 + 29) * 1.18


def _pmt(rate, nper, pv):
    """Excel PMT equivalent — returns negative payment amount."""
    if rate == 0:
        return -pv / nper
    return -pv * rate * (1 + rate) ** nper / ((1 + rate) ** nper - 1)


def _irr(cashflows, guess=0.1, tol=1e-8, max_iter=1000):
    """Newton's method IRR."""
    r = guess
    for _ in range(max_iter):
        npv = sum(cf / (1 + r) ** t for t, cf in enumerate(cashflows))
        dnpv = sum(-t * cf / (1 + r) ** (t + 1) for t, cf in enumerate(cashflows))
        if abs(dnpv) < 1e-14:
            break
        r_new = r - npv / dnpv
        if abs(r_new - r) < tol:
            return r_new
        r = r_new
    return r


def calc_termination(capacity_kwp, epc_per_wp, financing_per_wp, tariff,
                     escalation, yield_per_day, project_life):
    """
    Calculate termination (buyout) charges per kWp for years 1–25.

    Replicates the Excel model column-by-column:
      - Cashflows (EBITDA − tax) are built first in a single pass
      - ROI = IRR of the project cashflow series (computed once, exactly
        as the Excel's =IRR() cell does)
      - P-column (project balance) uses that single ROI throughout
      - IT-on-sale uses the closed-form solution Q = raw*0.34/(1−0.34)

    Parameters:
        capacity_kwp:     Plant capacity in kWp
        epc_per_wp:       Total EPC/Wp (DC) including GST, in Rs
        financing_per_wp: Financing cost per Wp in Rs
        tariff:           Solar tariff Rs/kWh
        escalation:       Tariff escalation rate (0 = flat)
        yield_per_day:    kWh/kWp/day  (P50 generation yield)
        project_life:     Contract length in years (10 / 15 / 20 / 25)

    Returns:
        list of 25 floats — termination charge per kWp for each year.
        Years beyond project_life are 0.
    """
    if capacity_kwp <= 0:
        return [0.0] * 25

    total_cost     = (epc_per_wp + financing_per_wp) * capacity_kwp * 1000
    # irradiation = yield * 365 / PR  so that gen = cap * irr * PR = cap * yield * 365
    irradiation    = yield_per_day * 365 / PR_RATIO
    om_base        = _om_base(capacity_kwp)          # Rs/kWp/yr before escalation
    # Excel model: loan = 100% of total project cost (not 70%)
    # The LOAN_FRACTION constant is not used here — the termination model
    # is an investor-buyout model where full cost is debt-financed for IRR purposes.
    loan_amount    = total_cost                       # 100% of cost
    tenor_int      = 15                               # fixed 15-year debt tenor (Excel)
    emi            = _pmt(INTEREST_RATE, tenor_int, loan_amount) if loan_amount > 0 else 0
    dep_co_rate    = 1.0 / project_life if project_life > 0 else 0

    n = 26   # index 0 = year 0, index 1..25 = years 1..25

    # ── initialise all arrays ────────────────────────────────────────────────
    pr          = [0.0] * n
    gen         = [0.0] * n
    tariff_arr  = [0.0] * n
    revenue     = [0.0] * n
    om          = [0.0] * n
    insurance   = [0.0] * n
    equip_chg   = [0.0] * n
    ebitda      = [0.0] * n
    bv_close    = [0.0] * n   # book value (company act) closing
    it_close    = [0.0] * n   # book value (IT act) closing
    debt_open   = [0.0] * n
    debt_close  = [0.0] * n
    debt_int    = [0.0] * n
    net_income  = [0.0] * n
    cum_losses  = [0.0] * n
    tax         = [0.0] * n
    cf_net      = [0.0] * n   # project cashflow (EBITDA − tax)
    p_close     = [0.0] * n   # P-column: running project balance
    it_on_sale  = [0.0] * n
    sale_value  = [0.0] * n
    term_kwp    = [0.0] * n

    # ── year 0 ───────────────────────────────────────────────────────────────
    bv_close[0]   = total_cost
    it_close[0]   = total_cost
    cf_net[0]     = -total_cost
    p_close[0]    = total_cost
    sale_value[0] = total_cost
    debt_open[0]  = loan_amount
    debt_close[0] = loan_amount

    # ── PASS 1: build all cashflows (no P-column yet) ────────────────────────
    for y in range(1, n):
        active = (y <= project_life)

        # PR and generation
        pr[y]  = PR_RATIO if y == 1 else pr[y-1] * (1 - DEGRADATION)
        gen[y] = capacity_kwp * irradiation * pr[y] if active else 0.0

        # Tariff (escalates each year while active)
        if y == 1:
            tariff_arr[y] = tariff if active else 0.0
        else:
            tariff_arr[y] = tariff_arr[y-1] * (1 + escalation) if active else 0.0

        revenue[y]  = gen[y] * tariff_arr[y] * (1 - BAD_DEBTS)

        # O&M — escalates 5% p.a.
        if y == 1:
            om[y] = om_base * capacity_kwp if active else 0.0
        else:
            om[y] = om[y-1] * (1 + OM_ESCALATION) if active else 0.0

        # Insurance on opening company-act book value
        bv_open_y   = bv_close[y-1]
        insurance[y] = bv_open_y * INSURANCE_RATE if (y <= 12 or active) else 0.0

        # Equipment change — 1% of total cost from yr 11 onwards
        equip_chg[y] = total_cost * EQUIPMENT_CHANGE_RATE if (y > 10 and active) else 0.0

        ebitda[y] = revenue[y] - om[y] - insurance[y] - equip_chg[y]

        # Company-act book value (straight-line over project_life)
        bv_dep_y    = total_cost * dep_co_rate if (bv_open_y > 0 and active) else 0.0
        bv_close[y] = max(bv_open_y - bv_dep_y, 0.0)

        # IT-act book value (WDV: 40% p.a., +20% additional in yr 1)
        it_open_y = it_close[y-1] if active else 0.0
        if y == 1:
            it_dep_y = it_open_y * (DEP_IT_ACT + ADDITIONAL_DEP)
        else:
            it_dep_y = it_open_y * DEP_IT_ACT
        it_close[y] = max(it_open_y - it_dep_y, 0.0)

        # Debt service
        debt_open[y]  = debt_close[y-1]
        debt_int[y]   = debt_open[y] * INTEREST_RATE
        debt_emi_y    = emi if debt_open[y] > 0 else 0.0
        debt_close[y] = max(debt_open[y] + debt_int[y] + debt_emi_y, 0.0)

        # Net income and cumulative losses (for tax-loss carry-forward)
        net_income[y] = ebitda[y] - it_dep_y - debt_int[y]
        cum_losses[y] = (net_income[y] if y == 1
                         else min(cum_losses[y-1] + net_income[y], 0.0))

        # Tax — only when cumulative losses are fully recovered
        tax[y] = net_income[y] * TAX_RATE if cum_losses[y] >= 0 else 0.0

        cf_net[y] = ebitda[y] - tax[y]

    # ── Compute ROI = IRR of project cashflows (exactly as Excel =IRR()) ─────
    roi = _irr(cf_net, guess=0.10)

    # ── PASS 2: P-column using the computed ROI ──────────────────────────────
    for y in range(1, n):
        p_open_y    = p_close[y-1]
        p_return_y  = p_open_y * roi
        p_close[y]  = p_open_y + p_return_y - cf_net[y]

        # IT on sale — closed form: Q = max(raw*r/(1-r), 0) where r = IT_ON_SALE_RATE
        raw = p_close[y] - it_close[y] + cum_losses[y]
        it_on_sale[y] = (raw * IT_ON_SALE_RATE / (1 - IT_ON_SALE_RATE)
                         if raw > 0 else 0.0)

        sale_value[y] = p_close[y] + it_on_sale[y]
        term_kwp[y]   = sale_value[y] / capacity_kwp

    # ── Return years 1–25 ────────────────────────────────────────────────────
    return [term_kwp[y] if y <= project_life else 0.0 for y in range(1, 26)]



def num_to_words_indian(amount):
    """
    Convert a number to Indian rupees in words.
    e.g. 13522500 -> "Rupees One Crore Thirty Five Lakh Twenty Two Thousand Five Hundred Only"
    """
    if amount is None:
        return ""
    try:
        amount = int(round(float(str(amount).replace(",", ""))))
    except Exception:
        return ""
    if amount == 0:
        return "Rupees Zero Only"

    ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine",
            "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen",
            "Seventeen", "Eighteen", "Nineteen"]
    tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]

    def _two(n):
        if n < 20:
            return ones[n]
        return (tens[n // 10] + (" " + ones[n % 10] if n % 10 else "")).strip()

    def _three(n):
        if n >= 100:
            return ones[n // 100] + " Hundred" + (" " + _two(n % 100) if n % 100 else "")
        return _two(n)

    parts = []
    crore = amount // 10_000_000;  amount %= 10_000_000
    lakh  = amount // 100_000;     amount %= 100_000
    thous = amount // 1_000;       amount %= 1_000
    hunds = amount

    if crore: parts.append(_three(crore) + " Crore")
    if lakh:  parts.append(_two(lakh)    + " Lakh")
    if thous: parts.append(_three(thous) + " Thousand")
    if hunds: parts.append(_three(hunds))

    return "Rupees " + " ".join(parts) + " Only"

def fmt_indian(val, decimals=0):
    """Format number with Indian grouping (10,26,277)."""
    if val is None:
        return ""
    neg = val < 0
    val = abs(val)
    if decimals > 0:
        s = f"{val:,.{decimals}f}"
    else:
        s = f"{int(round(val)):,}"
    parts = s.split(".")
    int_str = parts[0].replace(",", "")
    if len(int_str) <= 3:
        grouped = int_str
    else:
        head, tail = int_str[:-3], int_str[-3:]
        chunks = []
        while len(head) > 2:
            chunks.insert(0, head[-2:])
            head = head[:-2]
        if head:
            chunks.insert(0, head)
        grouped = ",".join(chunks + [tail])
    result = grouped + ("." + parts[1] if len(parts) > 1 and decimals > 0 else "")
    return ("-" + result) if neg else result


def fmt_cap(val):
    """
    Format capacity (kWp) with exact decimal precision — no rounding.
    654.92 → '654.92'   1480.0 → '1,480'   4952.61 → '4,952.61'
    Uses Indian grouping for the integer part.
    Strips trailing zeros after decimal point.
    """
    if val is None:
        return ""
    # Represent with enough decimal places, then strip trailing zeros
    s = f"{abs(float(val)):.6f}".rstrip("0").rstrip(".")
    int_part, _, dec_part = s.partition(".")
    # Apply Indian grouping to integer part
    if len(int_part) <= 3:
        grouped = int_part
    else:
        head, tail = int_part[:-3], int_part[-3:]
        chunks = []
        while len(head) > 2:
            chunks.insert(0, head[-2:])
            head = head[:-2]
        if head:
            chunks.insert(0, head)
        grouped = ",".join(chunks + [tail])
    return grouped + ("." + dec_part if dec_part else "")


# ── CAPEX Financial Model ────────────────────────────────────
# Replicates the "Inputs and Output" + "Workings" sheets

def _pmt(rate, nper, pv):
    """Excel PMT — returns negative payment."""
    if rate == 0: return -pv / nper
    return -pv * rate * (1 + rate)**nper / ((1 + rate)**nper - 1)


def _irr(cashflows, guess=0.1, tol=1e-8, max_iter=1000):
    """Newton's method IRR."""
    r = guess
    for _ in range(max_iter):
        npv = sum(cf / (1 + r)**t for t, cf in enumerate(cashflows))
        dnpv = sum(-t * cf / (1 + r)**(t + 1) for t, cf in enumerate(cashflows))
        if abs(dnpv) < 1e-14: break
        r_new = r - npv / dnpv
        if abs(r_new - r) < tol: return r_new
        r = r_new
    return r


def _npv(rate, cashflows):
    """NPV of cashflows (starting at period 1)."""
    return sum(cf / (1 + rate)**i for i, cf in enumerate(cashflows, 1))


def calc_capex_financials(
    capacity_kwp,
    epc_wp_excl_gst,
    project_life=25,
    inverter_life=5,
    om_cost_per_kwp=650,
    om_escalation=0.05,
    daily_gen=3.6,
    insurance_rate=0.002,
    equipment_change_rate=0.01,
    gst_credit=True,
    new_tax=True,
    commissioning="Apr-Sept",
    degradation_yr0=0, degradation_yr1=0.006,
    degradation_yr2_11=0.006, degradation_yr12_25=0.006,
    dep_rate=0.40,
    discount_rate=0.12,
    eb_tariff=7.08,
    eb_escalation=0.02,
    debt_pct=0.70,
    interest_rate=0.10,
    debt_tenure=10,
):
    """
    Full CAPEX financial model. Returns dict with all outputs matching the
    "Inputs and Output" sheet OUTPUT section + intermediate values.
    """
    # GST and project cost
    gst_per_wp = epc_wp_excl_gst * 0.089
    project_cost_wp = epc_wp_excl_gst + gst_per_wp  # incl GST
    system_cost = capacity_kwp * project_cost_wp * 1000  # total Rs
    co_act_dep_rate = 0.1129  # Companies Act depreciation (SLM approximation)

    # Tax rate
    if new_tax:
        tax_rate = 0.22 * 1.12 * 1.04  # ~25.6%
    else:
        tax_rate = 0.30 * 1.12 * 1.04  # ~34.9%

    # Additional depreciation
    add_dep = not new_tax  # AD only if old tax regime

    # Annual generation year 1
    gen_yr1 = capacity_kwp * daily_gen * 365

    # AMC cost year 1
    amc_yr1 = capacity_kwp * om_cost_per_kwp

    # ── AD Benefit / WDV Depreciation schedule (IT Act) ──
    # G = Opening, H = Depreciation, I = Closing WDV, J = Tax benefit
    n = 26  # years 0..25
    ad_open = [0.0] * n
    ad_dep = [0.0] * n
    ad_close = [0.0] * n
    ad_benefit = [0.0] * n

    if gst_credit:
        ad_open[0] = capacity_kwp * epc_wp_excl_gst * 1000  # excl GST
    else:
        ad_open[0] = system_cost  # incl GST

    # Year 0 depreciation
    if commissioning == "Apr-Sept":
        ad_dep[0] = ad_open[0] * (dep_rate + (0.20 if add_dep else 0))
    else:  # Oct-Mar: half rate
        ad_dep[0] = ad_open[0] * ((dep_rate / 2) + (0.20 if add_dep else 0))
    ad_close[0] = ad_open[0] - ad_dep[0]
    ad_benefit[0] = ad_dep[0] * tax_rate

    # Year 1 special
    ad_open[1] = ad_close[0]
    if commissioning == "Oct-Mar":
        # Catch-up for the half-year depreciation not claimed in Year 0
        # (Excel Workings!H5: =(G5*dep_rate)+(G4*10%) — a QUARTER of the
        # full-year rate on the original Year-0 opening value, not a half).
        ad_dep[1] = ad_open[1] * dep_rate + ad_open[0] * dep_rate / 4
    else:
        ad_dep[1] = ad_open[1] * dep_rate
    ad_close[1] = ad_open[1] - ad_dep[1]
    ad_benefit[1] = ad_dep[1] * tax_rate

    for y in range(2, n):
        ad_open[y] = ad_close[y - 1]
        ad_dep[y] = ad_open[y] * dep_rate
        ad_close[y] = ad_open[y] - ad_dep[y]
        ad_benefit[y] = ad_dep[y] * tax_rate

    # ── Companies Act Book Value (for insurance) ──
    bv_open = [0.0] * n
    bv_dep = [0.0] * n
    bv_close = [0.0] * n
    bv_open[0] = ad_open[0]  # same starting point
    bv_dep[0] = bv_open[0] * co_act_dep_rate
    bv_close[0] = bv_open[0] - bv_dep[0]
    for y in range(1, n):
        bv_open[y] = bv_close[y - 1]
        bv_dep[y] = bv_open[y] * co_act_dep_rate
        bv_close[y] = max(bv_open[y] - bv_dep[y], 0)

    # ── Debt Schedule ──
    loan = system_cost * debt_pct
    debt_open = [0.0] * n
    debt_emi = [0.0] * n
    debt_interest = [0.0] * n
    debt_principal = [0.0] * n
    debt_close = [0.0] * n
    debt_check = [0] * n  # 1 if within tenure

    debt_close[0] = loan
    emi_val = _pmt(interest_rate, debt_tenure, -loan) if loan > 0 else 0

    for y in range(1, n):
        debt_open[y] = debt_close[y - 1]
        debt_check[y] = 1 if y <= debt_tenure else 0
        if debt_open[y] > 0 and debt_check[y]:
            debt_interest[y] = debt_open[y] * interest_rate
            debt_emi[y] = emi_val if y == 1 else (debt_emi[y-1] * debt_check[y])
            debt_principal[y] = debt_emi[y] - debt_interest[y]
            debt_close[y] = max(debt_open[y] - debt_principal[y], 0)

    # ── GST Input Credit ──
    gst_credit_val = capacity_kwp * gst_per_wp * 1000 if gst_credit else 0

    # Tax benefit of depreciation in year 0
    tax_benefit_yr0 = ad_benefit[0]

    # ── 25-year Cashflow Model ──
    # Degradation schedule
    deg = [0.0] * n
    cum_deg = [0.0] * n
    deg[1] = degradation_yr0  # year 1 uses year 0 degradation (=0 typically)
    cum_deg[1] = deg[1]
    for y in range(2, n):
        if y <= 1: deg[y] = degradation_yr1
        elif y <= 11: deg[y] = degradation_yr2_11
        else: deg[y] = degradation_yr12_25
        cum_deg[y] = cum_deg[y - 1] + deg[y]

    generation = [0.0] * n
    generation[1] = gen_yr1
    for y in range(2, n):
        generation[y] = gen_yr1 * (1 - cum_deg[y])

    eb_tariff_arr = [0.0] * n
    eb_tariff_arr[1] = eb_tariff
    for y in range(2, n):
        eb_tariff_arr[y] = eb_tariff_arr[y - 1] * (1 + eb_escalation)

    grid_cost = [0.0] * n
    grid_cost_post_tax = [0.0] * n
    amc = [0.0] * n
    insurance = [0.0] * n
    equip_replace = [0.0] * n
    total_opex = [0.0] * n
    total_opex_tax = [0.0] * n
    dep_tax_benefit = [0.0] * n
    gst_benefit = [0.0] * n
    cost_solar_eq = [0.0] * n  # equity
    cost_solar_proj = [0.0] * n  # project
    net_savings_eq = [0.0] * n
    cum_savings_eq = [0.0] * n
    net_savings_proj = [0.0] * n
    cum_savings_proj = [0.0] * n

    # Year 0 for equity
    cost_solar_eq[0] = system_cost * (1 - debt_pct)
    net_savings_eq[0] = grid_cost_post_tax[0] - cost_solar_eq[0]
    cum_savings_eq[0] = net_savings_eq[0]
    cost_solar_proj[0] = system_cost
    net_savings_proj[0] = grid_cost_post_tax[0] - cost_solar_proj[0]
    cum_savings_proj[0] = net_savings_proj[0]

    for y in range(1, n):
        if y > project_life:
            continue

        grid_cost[y] = generation[y] * eb_tariff_arr[y]
        grid_cost_post_tax[y] = grid_cost[y] * (1 - tax_rate)

        amc[y] = amc_yr1 * ((1 + om_escalation) ** (y - 1))
        # One-year lag: see dep_tax_benefit note above — same lag pattern
        # applies to insurance's book-value base (Excel Workings!J-column).
        insurance[y] = bv_open[y - 1] * insurance_rate if y <= project_life else 0

        # Equipment replacement from year (inverter_life + 1) onwards
        if y > inverter_life:
            equip_replace[y] = system_cost * equipment_change_rate
        else:
            equip_replace[y] = 0

        total_opex[y] = amc[y] + insurance[y] + equip_replace[y] + debt_interest[y]
        total_opex_tax[y] = total_opex[y] * tax_rate
        # One-year lag: cashflow year Y uses the depreciation tax benefit
        # computed for AD-schedule year (Y-1), per Excel Workings!O-column.
        dep_tax_benefit[y] = ad_benefit[y - 1]
        gst_benefit[y] = gst_credit_val if y == 1 else 0

        # Equity cost of solar
        cost_solar_eq[y] = total_opex[y] - total_opex_tax[y] - dep_tax_benefit[y] - gst_benefit[y]
        net_savings_eq[y] = grid_cost_post_tax[y] - cost_solar_eq[y] - (debt_principal[y] if y <= debt_tenure else 0)
        cum_savings_eq[y] = cum_savings_eq[y - 1] + net_savings_eq[y]

        # Project cost of solar (no debt)
        proj_opex = amc[y] + insurance[y] + equip_replace[y]
        proj_opex_tax = proj_opex * tax_rate
        cost_solar_proj[y] = proj_opex - proj_opex_tax - dep_tax_benefit[y] - gst_benefit[y]
        net_savings_proj[y] = grid_cost_post_tax[y] - cost_solar_proj[y]
        cum_savings_proj[y] = cum_savings_proj[y - 1] + net_savings_proj[y]

    # Payback — project basis (Excel Workings!D16 = MIN(AB36:AB60), which is
    # built from the project-side Y/Z columns — full system cost recovered
    # against project (debt-free) savings, not the equity-only investment).
    payback = project_life
    for y in range(1, n):
        if cum_savings_proj[y] >= 0 and cum_savings_proj[y - 1] < 0:
            # Interpolate
            payback = y - cum_savings_proj[y] / net_savings_proj[y] if net_savings_proj[y] != 0 else y
            break

    # IRR (project)
    proj_cf = [net_savings_proj[0]] + [net_savings_proj[y] for y in range(1, project_life + 1)]
    try:
        project_irr = _irr(proj_cf, guess=0.1)
    except:
        project_irr = 0

    # IRR (equity)
    eq_cf = [net_savings_eq[0]] + [net_savings_eq[y] for y in range(1, project_life + 1)]
    try:
        equity_irr = _irr(eq_cf, guess=0.15)
    except:
        equity_irr = 0

    # Levelised cost
    # Year-0 term = full system cost (Excel Workings!X35 = D4), then
    # years 1..project_life = cost_solar_proj — matching Excel's NPV ranges
    # (X35:X60 vs E36:E60), which are intentionally offset by one year.
    cost_cf = [system_cost] + [cost_solar_proj[y] for y in range(1, project_life + 1)]
    gen_cf = [generation[y] for y in range(1, project_life + 1)]
    npv_cost = _npv(discount_rate, cost_cf)
    npv_gen = _npv(discount_rate, gen_cf)
    levelised_cost = npv_cost / npv_gen if npv_gen != 0 else 0

    # Net savings over project life (years 1..project_life only — Excel
    # Workings!R61 = SUM(R36:R60), excluding the Year-0 equity outlay R35)
    total_net_savings = sum(net_savings_eq[y] for y in range(1, project_life + 1))
    total_units = sum(generation[y] for y in range(1, project_life + 1))

    # Net cost to client
    net_cost = system_cost - tax_benefit_yr0 - gst_credit_val

    return {
        "system_size_kwp": capacity_kwp,
        "system_cost_lacs": system_cost / 1e5,
        "gst_credit_lacs": gst_credit_val / 1e5,
        "net_cost_lacs": net_cost / 1e5,
        "amc_cost_lacs": amc_yr1 / 1e5,
        "gen_yr1": gen_yr1,
        "eb_tariff": eb_tariff,
        "eb_escalation": eb_escalation,
        "savings_yr1_lacs": net_savings_eq[1] / 1e5 if len(net_savings_eq) > 1 else 0,
        "payback_years": payback,
        "project_life": project_life,
        "inverter_life": inverter_life,
        "net_savings_lacs": total_net_savings / 1e5,
        "total_units_lacs": total_units / 1e5,
        "project_irr": project_irr,
        "equity_irr": equity_irr,
        "levelised_cost": levelised_cost,
        "investment_cr": system_cost / 1e7,
        "gst_per_wp": gst_per_wp,
        "project_cost_wp": project_cost_wp,
        "total_cost": system_cost,
        "co2_tons": gen_yr1 * ENV_CO2 / 1000,
        "tax_rate": tax_rate,
    }
