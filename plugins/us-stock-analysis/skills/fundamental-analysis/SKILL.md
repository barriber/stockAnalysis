---
name: fundamental-analysis
description: Conduct deep-dive fundamental analysis using income statement, balance sheet, and cash flow statement. Use when the user asks "fundamental analysis of X", "analyze X's financials", "is X profitable", "earnings quality of X", "ROIC and margins for X", or wants a financial-statement-driven view of business quality.
---

# Fundamental Analysis

Conduct deep-dive fundamental analysis of US stocks using financial statements and business metrics.

## Step 0: Fetch Live Data (required)

Before any analysis, fetch verified live numerics so this skill never anchors on
training-cutoff knowledge for revenue, margins, or returns on capital:

```
/us-stock-analysis:fetch-stock-data <TICKER> --fields=price,market_cap,ttm_revenue,ttm_gross_profit,ttm_op_income,ttm_net_income,ttm_eps,op_margin,net_margin,fcf_margin,rev_cagr_3y,rev_cagr_5y,rev_cagr_10y,eps_cagr_5y,roe,roa,roic,total_equity,total_debt,diluted_shares
```

Parse the returned JSON envelope and use `data.<field>.v` for every numeric input
below. If a field appears in `missing[]` or `errors[]`, fall back to the most recent
published 10-K/10-Q value and explicitly flag it as
"LLM-derived; verify against latest filing" in the final analysis.

**Fields not yet exposed by `financial-manager`** (will appear in `missing[]`):

- `gross_margin` — derive as `ttm_gross_profit / ttm_revenue`.
- `pb`, `ps`, `ev_ebitda` — flag as LLM-derived in the multiples table.

---

## Financial Statement Analysis

1. **Income Statement Analysis**
   - Revenue breakdown and growth drivers
   - Cost structure and margin trends
   - Operating leverage analysis
   - Earnings quality assessment
   - Non-recurring items identification

2. **Balance Sheet Analysis**
   - Asset quality and composition
   - Liability structure and debt maturity
   - Working capital management
   - Off-balance sheet items
   - Shareholder equity trends

3. **Cash Flow Statement Analysis**
   - Operating cash flow generation
   - Capital expenditure requirements
   - Free cash flow calculation
   - Cash conversion cycle
   - Financing and investing activities

## Business Quality Metrics

1. **Profitability Analysis**
   - Gross margin trends
   - Operating margin consistency
   - Net profit margins
   - ROE, ROA, ROIC trends

2. **Growth Analysis**
   - Historical growth rates (3, 5, 10 years)
   - Growth quality (organic vs. acquisitions)
   - Market share trends
   - Geographic and product segment analysis

3. **Efficiency Metrics**
   - Asset turnover ratios
   - Inventory management
   - Receivables collection
   - Fixed asset productivity

4. **Capital Allocation**
   - Dividend policy and sustainability
   - Share buyback programs
   - M&A strategy and execution
   - R&D and capex investments

## Competitive Analysis

- Porter's Five Forces assessment
- Competitive moat identification
- Industry structure and dynamics
- Market share trends
- Pricing power evaluation

## Visualization Support

When `--visual` flag is used, include chart data tables for key metrics:

### 1. Revenue & Earnings Growth Chart
**Chart Type**: Line chart with dual Y-axis
**Data Table**:
```
Year      Revenue ($M)    Revenue Growth %    Net Income ($M)    EPS ($)
Year-4    [value]         [%]                 [value]            [value]
Year-3    [value]         [%]                 [value]            [value]
Year-2    [value]         [%]                 [value]            [value]
Year-1    [value]         [%]                 [value]            [value]
Year      [value]         [%]                 [value]            [value]
```

### 2. Profit Margin Trends
**Chart Type**: Line chart with percentage Y-axis
**Data Table**:
```
Year      Gross Margin %    Operating Margin %    Net Margin %    Industry Avg %
Year-4    [%]              [%]                   [%]             [%]
Year-3    [%]              [%]                   [%]             [%]
Year-2    [%]              [%]                   [%]             [%]
Year-1    [%]              [%]                   [%]             [%]
Year      [%]              [%]                   [%]             [%]
```

### 3. Balance Sheet Composition
**Chart Type**: Stacked bar chart
**Data Table**:
```
Year      Current Assets ($M)    Fixed Assets ($M)    Intangibles ($M)    Total Assets ($M)
Year-4    [value]               [value]              [value]             [value]
Year-3    [value]               [value]              [value]             [value]
Year-2    [value]               [value]              [value]             [value]
Year-1    [value]               [value]              [value]             [value]
Year      [value]               [value]              [value]             [value]

Year      Current Liab ($M)    Long-term Debt ($M)    Equity ($M)    Total L+E ($M)
Year-4    [value]             [value]                [value]        [value]
Year-3    [value]             [value]                [value]        [value]
Year-2    [value]             [value]                [value]        [value]
Year-1    [value]             [value]                [value]        [value]
Year      [value]             [value]                [value]        [value]
```

### 4. Cash Flow Waterfall
**Chart Type**: Waterfall chart
**Data Table**:
```
Component                   Amount ($M)    Notes
Operating Cash Flow         [value]        Core business generation
Capital Expenditures        [value]        Investments in assets
Free Cash Flow             [value]        Available for distribution
Dividends                  [value]        Shareholder distribution
Share Buybacks             [value]        Share repurchases
M&A Activity               [value]        Acquisitions
Debt Repayment             [value]        Debt reduction
Net Cash Change            [value]        Bottom line impact
```

### 5. Valuation Multiples Comparison
**Chart Type**: Grouped bar chart
**Data Table**:
```
Metric              Company    Industry Avg    5-Year Avg    Assessment
P/E Ratio           [value]    [value]         [value]       [Over/Under/Fair]
P/B Ratio           [value]    [value]         [value]       [Over/Under/Fair]
P/S Ratio           [value]    [value]         [value]       [Over/Under/Fair]
EV/EBITDA          [value]    [value]         [value]       [Over/Under/Fair]
PEG Ratio          [value]    [value]         [value]       [Over/Under/Fair]
```

### ASCII Chart Example (Terminal Display)
When visual charts aren't available, provide ASCII charts for key metrics:

```
Revenue Growth (5-Year Trend)
$250B ┤                                          ╭──
$200B ┤                                   ╭──────╯
$150B ┤                            ╭──────╯
$100B ┤                     ╭──────╯
$50B  ┤              ╭──────╯
      └──────┬───────┬───────┬───────┬───────┬──
          Year-4  Year-3  Year-2  Year-1   Year
```

### Integration with Report Generator
When `--visual` flag is used, output is optimized for `/report-generator` skill:
- Data tables formatted for Chart.js ingestion
- Chart type recommendations included
- Color coding suggestions (green for positive, red for negative)
- Axis labels and units clearly specified

## Output

Provide detailed fundamental report with:
- Financial strength score
- Business quality rating
- Competitive position assessment
- Key investment risks
- Fair value estimate with methodology
- Investment recommendation with time horizon

### Enhanced Output (with --visual flag)
- All standard output sections above
- Chart data tables for 5 key visualization areas
- ASCII charts for terminal display
- Chart specifications for HTML report generation
- Color-coded metrics (green/red for positive/negative trends)

## Standard Signal Output

All analysis concludes with this standardized block:

```
╔══════════════════════════════════════════════╗
║              INVESTMENT SIGNAL               ║
╠══════════════════════════════════════════════╣
║ Signal:      BULLISH / NEUTRAL / BEARISH     ║
║ Confidence:  HIGH / MEDIUM / LOW             ║
║ Horizon:     SHORT / MEDIUM / LONG-TERM      ║
║ Score:       X.X / 10                        ║
╠══════════════════════════════════════════════╣
║ Action:      BUY / HOLD / SELL               ║
║ Conviction:  STRONG / MODERATE / WEAK        ║
╚══════════════════════════════════════════════╝
```

**Score Guide**: 8.0–10.0 Strongly Bullish | 6.0–7.9 Moderately Bullish | 4.0–5.9 Neutral | 2.0–3.9 Moderately Bearish | 0.0–1.9 Strongly Bearish
**Confidence**: HIGH (strong data, clear signals) | MEDIUM (mixed signals) | LOW (limited data, conflicting signals)
**Horizon**: SHORT-TERM (1 week–3 months) | MEDIUM-TERM (3 months–1 year) | LONG-TERM (1+ years)
