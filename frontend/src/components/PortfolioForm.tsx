"use client";

import { useState, useEffect } from "react";
import type { Portfolio, AssetGroup } from "@/lib/types";
import { fetchDemoPortfolios } from "@/lib/api";

interface Props {
  onAnalyse: (portfolio: Portfolio) => void;
  loading: boolean;
}

const ASSET_TYPES = ["ev_charger", "battery", "generator", "heat_pump", "solar_pv", "ci_load"] as const;
const SERVICE_TYPES = ["demand_turn_down", "demand_turn_up", "generation_turn_up", "generation_turn_down"] as const;

const emptyAsset: AssetGroup = {
  source: "synthetic",
  asset_type: "ev_charger",
  asset_count: 100,
  rated_power_kw: 7,
  controllable_power_kw: 4.5,
  availability_percent: 0.03,
  response_reliability_percent: 0.85,
  supported_service_types: ["demand_turn_down", "demand_turn_up"],
  regional_distribution: { UKPN: 0.5, SPEN: 0.2, NGED: 0.15, ENWL: 0.05, NPG: 0.05, SSEN: 0.05 },
  postcode_distribution: {},
  baseline_assumption: "",
  metering_assumption: "",
  operational_notes: [],
};

export default function PortfolioForm({ onAnalyse, loading }: Props) {
  const [portfolios, setPortfolios] = useState<Portfolio[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [custom, setCustom] = useState<Portfolio>({
    portfolio_id: "custom_001",
    portfolio_name: "My Custom Portfolio",
    assets: [{ ...emptyAsset }],
  });
  const [mode, setMode] = useState<"select" | "custom">("select");

  useEffect(() => {
    fetchDemoPortfolios().then(setPortfolios).catch(console.error);
  }, []);

  const handleSelect = (id: string) => {
    setSelected(id);
    const p = portfolios.find((p) => p.portfolio_id === id);
    if (p) setCustom(p);
  };

  const handleSubmit = () => {
    const portfolio = mode === "select"
      ? portfolios.find((p) => p.portfolio_id === selected) || custom
      : custom;
    onAnalyse(portfolio);
  };

  const updateAsset = (idx: number, field: keyof AssetGroup, value: unknown) => {
    const assets = [...custom.assets];
    assets[idx] = { ...assets[idx], [field]: value };
    setCustom({ ...custom, assets });
  };

  return (
    <div className="bg-surface rounded-lg shadow-card p-6">
      <h2 className="text-lg font-bold mb-4 text-gray-900">Portfolio Input</h2>

      {/* Mode toggle */}
      <div className="flex gap-2 mb-4">
        <button
          onClick={() => setMode("select")}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors duration-150 ${
            mode === "select" ? "bg-brand-600 text-white" : "bg-surface-muted text-gray-600 hover:bg-gray-200"
          }`}
        >
          Select Example
        </button>
        <button
          onClick={() => setMode("custom")}
          className={`px-4 py-2 rounded-lg text-sm font-medium transition-colors duration-150 ${
            mode === "custom" ? "bg-brand-600 text-white" : "bg-surface-muted text-gray-600 hover:bg-gray-200"
          }`}
        >
          Custom Portfolio
        </button>
      </div>

      {mode === "select" && (
        <div className="mb-4">
          <label className="block text-sm font-medium text-gray-700 mb-1">Example Portfolios</label>
          <select
            value={selected}
            onChange={(e) => handleSelect(e.target.value)}
            className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-brand-500"
          >
            <option value="">— Select a portfolio —</option>
            {portfolios.map((p) => (
              <option key={p.portfolio_id} value={p.portfolio_id}>
                {p.portfolio_name} ({p.assets.length} asset group{p.assets.length > 1 ? "s" : ""})
              </option>
            ))}
          </select>
        </div>
      )}

      {mode === "custom" && (
        <div className="space-y-4 mb-4">
          <div>
            <label className="block text-sm font-medium text-gray-700 mb-1">Portfolio Name</label>
            <input
              type="text"
              value={custom.portfolio_name}
              onChange={(e) => setCustom({ ...custom, portfolio_name: e.target.value })}
              className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500 focus:border-brand-500"
            />
          </div>

          {custom.assets.map((asset, idx) => (
            <div key={idx} className="border border-gray-200 rounded-lg p-4 bg-surface-muted">
              <h3 className="text-sm font-semibold mb-3 text-gray-700">Asset Group {idx + 1}</h3>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Asset Type</label>
                  <select
                    value={asset.asset_type}
                    onChange={(e) => updateAsset(idx, "asset_type", e.target.value)}
                    className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                  >
                    {ASSET_TYPES.map((t) => (
                      <option key={t} value={t}>{t.replace(/_/g, " ")}</option>
                    ))}
                  </select>
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Asset Count</label>
                  <input
                    type="number"
                    value={asset.asset_count}
                    onChange={(e) => updateAsset(idx, "asset_count", Number(e.target.value))}
                    className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Controllable Power (kW)</label>
                  <input
                    type="number"
                    step="0.1"
                    value={asset.controllable_power_kw}
                    onChange={(e) => updateAsset(idx, "controllable_power_kw", Number(e.target.value))}
                    className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                  />
                </div>
                <div>
                  <label className="block text-xs text-gray-500 mb-1">Availability (%)</label>
                  <input
                    type="number"
                    step="0.01"
                    value={asset.availability_percent}
                    onChange={(e) => updateAsset(idx, "availability_percent", Number(e.target.value))}
                    className="w-full border border-gray-200 rounded-lg px-2 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-brand-500"
                  />
                </div>
              </div>
            </div>
          ))}

          <button
            onClick={() =>
              setCustom({
                ...custom,
                assets: [...custom.assets, { ...emptyAsset, asset_type: "battery" }],
              })
            }
            className="text-sm text-brand-600 hover:text-brand-700 font-medium"
          >
            + Add another asset group
          </button>
        </div>
      )}

      <button
        onClick={handleSubmit}
        disabled={loading || (mode === "select" && !selected)}
        className="w-full bg-brand-600 text-white py-2.5 px-4 rounded-lg font-medium transition-colors duration-150 hover:bg-brand-700 focus:outline-none focus-visible:ring-2 focus-visible:ring-brand-500 focus-visible:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
      >
        {loading ? "Analysing…" : "Run Analysis — Synthetic Demo"}
      </button>
    </div>
  );
}
