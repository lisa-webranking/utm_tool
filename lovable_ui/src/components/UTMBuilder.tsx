import { useState } from "react";
import { motion, AnimatePresence } from "framer-motion";
import { Copy, ExternalLink, AlertTriangle, Info, ChevronDown, Check, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { toast } from "sonner";

const SOURCES = ["google", "facebook", "instagram", "linkedin", "newsletter", "258.com", "bing", "referral"];
const MEDIUMS = ["cpc", "cpm", "email", "social", "referral", "organic", "display", "affiliate"];

type UTMBuilderProps = {
  embedded?: boolean;
};

const UTMBuilder = ({ embedded = false }: UTMBuilderProps) => {
  const [activeTab, setActiveTab] = useState<"build" | "check" | "history">("build");
  const [protocol, setProtocol] = useState("https://");
  const [url, setUrl] = useState("");
  const [source, setSource] = useState("");
  const [medium, setMedium] = useState("");
  const [campaign, setCampaign] = useState("");
  const [campaignType, setCampaignType] = useState("");
  const [content, setContent] = useState("");
  const [term, setTerm] = useState("");
  const [startDate, setStartDate] = useState(new Date().toISOString().split("T")[0]);
  const [country, setCountry] = useState("");
  const [ga4Account, setGa4Account] = useState("webranking IT");
  const [ga4Property, setGa4Property] = useState("www.daimon.agency - GA4 (Produzione)");
  const [copied, setCopied] = useState(false);

  const generatedUrl = (() => {
    if (!url) return "";
    const params = new URLSearchParams();
    if (source) params.set("utm_source", source);
    if (medium) params.set("utm_medium", medium);
    if (campaign) params.set("utm_campaign", campaign);
    if (content) params.set("utm_content", content);
    if (term) params.set("utm_term", term);
    if (campaignType) params.set("campaign_type", campaignType);
    const queryString = params.toString();
    return `${protocol}${url}${queryString ? "?" + queryString : ""}`;
  })();

  const copyToClipboard = () => {
    if (!generatedUrl) {
      toast.error("Inserisci almeno l'URL di destinazione");
      return;
    }
    navigator.clipboard.writeText(generatedUrl);
    setCopied(true);
    toast.success("URL copiato negli appunti!");
    setTimeout(() => setCopied(false), 2000);
  };

  const resetForm = () => {
    setUrl("");
    setSource("");
    setMedium("");
    setCampaign("");
    setCampaignType("");
    setContent("");
    setTerm("");
    setCountry("");
    toast("Form resettato");
  };

  const tabs = [
    { id: "build" as const, label: "Build URL", count: null },
    { id: "check" as const, label: "Check URL", count: null },
    { id: "history" as const, label: "History", count: "0" },
  ];

  const trafficSources = ["Custom values", "Google Ads", "Social", "Email"];
  const [activeTrafficSource, setActiveTrafficSource] = useState("Custom values");

  const filledParams = [source, medium, campaign].filter(Boolean).length;

  return (
    <section className={embedded ? "px-3 py-6 sm:px-5" : "container mx-auto max-w-6xl px-6 py-14"}>
      {/* Tabs */}
      <div className="mb-10 flex items-center justify-center">
        <div className="inline-flex rounded-2xl border bg-card p-1 shadow-sm">
          {tabs.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`relative rounded-xl px-5 py-2 text-sm font-medium transition-all duration-200 ${
                activeTab === tab.id
                  ? "bg-primary text-primary-foreground shadow-md"
                  : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {tab.label}
              {tab.count && (
                <span className={`ml-1.5 inline-flex h-4 min-w-4 items-center justify-center rounded-full px-1 text-[10px] font-semibold ${
                  activeTab === tab.id ? "bg-primary-foreground/20 text-primary-foreground" : "bg-muted text-muted-foreground"
                }`}>
                  {tab.count}
                </span>
              )}
            </button>
          ))}
        </div>
      </div>

      <AnimatePresence mode="wait">
        {activeTab === "build" && (
          <motion.div
            key="build"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            transition={{ duration: 0.3 }}
          >
            {/* Title row */}
            <div className="mb-8 flex items-end justify-between">
              <div>
                <h2 className="mb-1 font-heading text-2xl font-bold tracking-tight sm:text-3xl">
                  Campaign URL Builder
                </h2>
                <p className="text-sm text-muted-foreground">
                  Seleziona la property GA4 per caricare source e medium reali.
                </p>
              </div>
              <div className="hidden items-center gap-2 sm:flex">
                <div className="flex items-center gap-1.5 rounded-lg bg-accent/10 px-3 py-1.5">
                  <div className={`h-2 w-2 rounded-full ${filledParams >= 3 ? 'bg-green-500' : filledParams > 0 ? 'bg-amber-400' : 'bg-muted-foreground/30'}`} />
                  <span className="text-xs font-medium text-accent">{filledParams}/3 required</span>
                </div>
                <Button variant="ghost" size="sm" onClick={resetForm} className="gap-1.5 text-muted-foreground">
                  <RotateCcw className="h-3.5 w-3.5" />
                  Reset
                </Button>
              </div>
            </div>

            {/* GA4 Selection Card */}
            <div className="mb-8 rounded-2xl border bg-card p-5 shadow-sm">
              <div className="mb-4 flex items-center gap-2">
                <div className="flex h-7 w-7 items-center justify-center rounded-lg bg-accent/15">
                  <BarChart3Icon className="h-3.5 w-3.5 text-accent" />
                </div>
                <span className="text-sm font-semibold">Collegamento GA4</span>
              </div>
              <div className="grid gap-4 sm:grid-cols-2">
                <FieldGroup label="GA4 Account">
                  <SelectField value={ga4Account} onChange={setGa4Account} options={["webranking IT"]} />
                </FieldGroup>
                <FieldGroup label="GA4 Property">
                  <SelectField value={ga4Property} onChange={setGa4Property} options={["www.daimon.agency - GA4 (Produzione)"]} prefix="90" />
                </FieldGroup>
              </div>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted-foreground/60">
                <span>Sorgenti: (direct), google, facebook.com, webranking.it, bing, 258.com</span>
                <span>Medium: (none), referral, organic</span>
              </div>
            </div>

            {/* URL Address Card */}
            <div className="mb-8 rounded-2xl border bg-card p-5 shadow-sm">
              <h3 className="mb-4 flex items-center gap-2 text-sm font-semibold">
                <span className="flex h-5 w-5 items-center justify-center rounded-md bg-primary text-[10px] font-bold text-primary-foreground">1</span>
                URL di destinazione
              </h3>
              <div className="flex gap-2">
                <SelectField value={protocol} onChange={setProtocol} options={["https://", "http://"]} className="w-[110px] shrink-0" />
                <Input placeholder="example.com/landing-page" value={url} onChange={(e) => setUrl(e.target.value)} className="bg-background" />
              </div>
              {url && !url.includes("/") && (
                <p className="mt-2 flex items-center gap-1.5 text-xs text-destructive">
                  <AlertTriangle className="h-3.5 w-3.5" />
                  Consigliato: inserisci un path (es. example.com/pagina)
                </p>
              )}
            </div>

            {/* Traffic Source Card */}
            <div className="mb-8 rounded-2xl border bg-card p-5 shadow-sm">
              <div className="mb-5 flex items-center justify-between">
                <h3 className="flex items-center gap-2 text-sm font-semibold">
                  <span className="flex h-5 w-5 items-center justify-center rounded-md bg-primary text-[10px] font-bold text-primary-foreground">2</span>
                  Parametri UTM
                </h3>
                <details className="group">
                  <summary className="cursor-pointer text-xs font-medium text-accent hover:text-accent/80">
                    Naming Convention ?
                  </summary>
                  <div className="absolute z-20 mt-2 w-72 rounded-xl border bg-popover p-4 text-xs text-muted-foreground shadow-lg">
                    Usa sempre lowercase, separatori con underscore, nomi coerenti e riconoscibili.
                  </div>
                </details>
              </div>

              {/* Traffic source tabs */}
              <div className="mb-6 flex flex-wrap gap-1.5">
                {trafficSources.map((ts) => (
                  <button
                    key={ts}
                    onClick={() => setActiveTrafficSource(ts)}
                    className={`rounded-lg px-3 py-1.5 text-xs font-medium transition-all ${
                      activeTrafficSource === ts
                        ? "bg-accent/15 text-accent ring-1 ring-accent/20"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    }`}
                  >
                    {ts}
                  </button>
                ))}
              </div>

              {/* Parameters grid */}
              <div className="grid gap-8 lg:grid-cols-2">
                {/* Required */}
                <div>
                  <div className="mb-4 flex items-center gap-2">
                    <span className="text-xs font-semibold uppercase tracking-wider text-foreground/70">Required</span>
                    <div className="h-px flex-1 bg-border" />
                  </div>
                  <div className="space-y-4">
                    <ParameterField tag="utm_source" sublabel="Campaign source" required>
                      <SelectField value={source} onChange={setSource} options={SOURCES} placeholder="Seleziona source..." />
                    </ParameterField>
                    <ParameterField tag="utm_medium" sublabel="Campaign medium" required>
                      <SelectField value={medium} onChange={setMedium} options={MEDIUMS} placeholder="Seleziona medium..." />
                    </ParameterField>
                    <ParameterField tag="utm_campaign" sublabel="Campaign name" required>
                      <Input placeholder="promo, discount, sale" value={campaign} onChange={(e) => setCampaign(e.target.value)} className="bg-background" />
                    </ParameterField>
                    <ParameterField tag="campaign_type" sublabel="Tipo campagna">
                      <Input placeholder="always on, promo, launch" value={campaignType} onChange={(e) => setCampaignType(e.target.value)} className="bg-background" />
                    </ParameterField>
                    <div className="grid grid-cols-2 gap-3">
                      <FieldGroup label="Data inizio">
                        <Input type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} className="bg-background" />
                      </FieldGroup>
                      <FieldGroup label="Country/Lingua">
                        <Input placeholder="it, en, de" value={country} onChange={(e) => setCountry(e.target.value)} className="bg-background" />
                      </FieldGroup>
                    </div>
                  </div>
                </div>

                {/* Optional */}
                <div>
                  <div className="mb-4 flex items-center gap-2">
                    <span className="text-xs font-semibold uppercase tracking-wider text-foreground/70">Optional</span>
                    <div className="h-px flex-1 bg-border" />
                  </div>
                  <div className="space-y-4">
                    <ParameterField tag="utm_content" sublabel="Campaign content">
                      <Input placeholder="cta, banner, image" value={content} onChange={(e) => setContent(e.target.value)} className="bg-background" />
                    </ParameterField>
                    <ParameterField tag="utm_term" sublabel="Campaign term">
                      <Input placeholder="keyword, prospecting, retargeting" value={term} onChange={(e) => setTerm(e.target.value)} className="bg-background" />
                    </ParameterField>
                  </div>
                </div>
              </div>
            </div>

            {/* Generated URL */}
            <AnimatePresence>
              {generatedUrl && (
                <motion.div
                  initial={{ opacity: 0, y: 10, scale: 0.98 }}
                  animate={{ opacity: 1, y: 0, scale: 1 }}
                  exit={{ opacity: 0, y: 10, scale: 0.98 }}
                  className="rounded-2xl border-2 border-accent/20 bg-accent/[0.04] p-5 shadow-sm"
                >
                  <div className="mb-3 flex items-center justify-between">
                    <h3 className="text-xs font-semibold uppercase tracking-wider text-accent">
                      URL Generato
                    </h3>
                    <div className="flex items-center gap-1.5">
                      <Button
                        onClick={copyToClipboard}
                        size="sm"
                        className="h-8 gap-1.5 rounded-lg bg-accent text-accent-foreground hover:bg-accent/90"
                      >
                        {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
                        {copied ? "Copiato!" : "Copia"}
                      </Button>
                      <Button
                        variant="outline"
                        size="sm"
                        className="h-8 gap-1.5 rounded-lg"
                        onClick={() => window.open(generatedUrl, "_blank")}
                      >
                        <ExternalLink className="h-3.5 w-3.5" />
                        Apri
                      </Button>
                    </div>
                  </div>
                  <code className="block overflow-x-auto rounded-xl bg-primary/5 px-4 py-3 text-xs leading-relaxed text-foreground selection:bg-accent/20">
                    {generatedUrl}
                  </code>
                </motion.div>
              )}
            </AnimatePresence>
          </motion.div>
        )}

        {activeTab === "check" && (
          <motion.div
            key="check"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="mx-auto max-w-2xl rounded-2xl border bg-card p-8 text-center shadow-sm"
          >
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-accent/10">
              <Info className="h-5 w-5 text-accent" />
            </div>
            <h2 className="mb-2 font-heading text-xl font-bold">Check URL</h2>
            <p className="mb-6 text-sm text-muted-foreground">Incolla un URL per verificare i parametri UTM.</p>
            <Input placeholder="https://example.com?utm_source=..." className="bg-background text-center" />
          </motion.div>
        )}

        {activeTab === "history" && (
          <motion.div
            key="history"
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -8 }}
            className="mx-auto max-w-2xl rounded-2xl border bg-card p-8 text-center shadow-sm"
          >
            <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-muted">
              <RotateCcw className="h-5 w-5 text-muted-foreground" />
            </div>
            <h2 className="mb-2 font-heading text-xl font-bold">UTM History</h2>
            <p className="text-sm text-muted-foreground">La cronologia dei tuoi UTM generati apparirà qui.</p>
          </motion.div>
        )}
      </AnimatePresence>
    </section>
  );
};

// --- Sub-components ---

const BarChart3Icon = ({ className }: { className?: string }) => (
  <svg className={className} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
    <line x1="12" x2="12" y1="20" y2="10" /><line x1="18" x2="18" y1="20" y2="4" /><line x1="6" x2="6" y1="20" y2="14" />
  </svg>
);

const FieldGroup = ({ label, children }: { label: string; children: React.ReactNode }) => (
  <div>
    <Label className="mb-1.5 block text-[11px] font-medium uppercase tracking-wider text-muted-foreground/70">
      {label}
    </Label>
    {children}
  </div>
);

const SelectField = ({
  value, onChange, options, placeholder, prefix, className,
}: {
  value: string; onChange: (v: string) => void; options: string[];
  placeholder?: string; prefix?: string; className?: string;
}) => (
  <div className={`relative ${className || ""}`}>
    <select
      value={value}
      onChange={(e) => onChange(e.target.value)}
      className="h-10 w-full appearance-none rounded-xl border bg-background px-3 pr-8 text-sm text-foreground transition-all focus:border-accent focus:outline-none focus:ring-2 focus:ring-ring/20"
    >
      {placeholder && <option value="">{placeholder}</option>}
      {options.map((opt) => (
        <option key={opt} value={opt}>
          {prefix ? `${prefix}  ${opt}` : opt}
        </option>
      ))}
    </select>
    <ChevronDown className="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground/50" />
  </div>
);

const ParameterField = ({
  tag, sublabel, required, children,
}: {
  tag: string; sublabel: string; required?: boolean; children: React.ReactNode;
}) => (
  <div>
    <div className="mb-1.5 flex items-center gap-2">
      <span className="text-xs font-medium text-muted-foreground">{sublabel}</span>
      {required && <span className="text-[10px] font-semibold text-destructive">*</span>}
    </div>
    <div className="flex items-center gap-2">
      <span className="shrink-0 rounded-lg bg-primary px-2.5 py-1.5 font-mono text-[11px] font-semibold text-primary-foreground">
        {tag}
      </span>
      <div className="flex-1">{children}</div>
    </div>
  </div>
);

export default UTMBuilder;


