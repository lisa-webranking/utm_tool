import { motion } from "framer-motion";
import {
  ArrowRight,
  Bot,
  MessageCircle,
  Sparkles,
  WandSparkles,
} from "lucide-react";

const openChatbot = () => {
  const chatButton = document.querySelector<HTMLElement>(
    '[data-testid="chat-widget-button"], .chat-widget-button, #chat-widget-button, ' +
      '[class*="chatbot"] button, [id*="chatbot"] button, ' +
      '[class*="chat-bubble"], [id*="chat-bubble"], ' +
      'iframe[title*="chat"], ' +
      '.tidio-trigger, #tidio-chat, ' +
      '.crisp-client button, ' +
      '[class*="intercom"], #intercom-container button, ' +
      '[data-id="zsalesforce"], ' +
      'button[aria-label*="chat" i], button[aria-label*="Chat" i]'
  );

  if (chatButton) {
    chatButton.click();
    return;
  }

  window.dispatchEvent(new CustomEvent("open-chatbot"));

  if ((window as any).tidioChatApi) (window as any).tidioChatApi.open();
  else if ((window as any).$crisp) (window as any).$crisp.push(["do", "chat:open"]);
  else if ((window as any).Intercom) (window as any).Intercom("show");
};

type HeroSectionProps = {
  onOpenManual: () => void;
};

const HeroSection = ({ onOpenManual }: HeroSectionProps) => {
  return (
    <section className="relative overflow-hidden bg-primary pb-16 pt-12 sm:pt-16">
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -left-20 -top-20 h-[400px] w-[400px] rounded-full bg-accent/8 blur-[120px]" />
        <div className="absolute -bottom-20 -right-20 h-[300px] w-[300px] rounded-full bg-accent/10 blur-[100px]" />
        <div className="absolute left-1/2 top-1/2 h-[200px] w-[200px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent/5 blur-[80px]" />
      </div>

      <div
        className="pointer-events-none absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage:
            "linear-gradient(hsl(var(--primary-foreground)) 1px, transparent 1px), linear-gradient(90deg, hsl(var(--primary-foreground)) 1px, transparent 1px)",
          backgroundSize: "60px 60px",
        }}
      />

      <div className="container relative z-10 mx-auto max-w-6xl px-6">
        <motion.div
          initial={{ opacity: 0, y: 18 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="mx-auto max-w-3xl text-center"
        >
          <div className="mb-5 inline-flex items-center gap-2 rounded-full border border-accent/20 bg-accent/10 px-4 py-1.5">
            <WandSparkles className="h-3.5 w-3.5 text-accent" />
            <span className="text-xs font-semibold text-accent">Modalita consigliata</span>
          </div>

          <h1 className="mb-3 font-heading text-3xl font-bold tracking-tight text-primary-foreground sm:text-4xl md:text-5xl">
            Crea i tuoi UTM in pochi secondi con l&apos;assistente
          </h1>

          <p className="mx-auto mb-9 max-w-2xl text-sm leading-relaxed text-primary-foreground/65 sm:text-base">
            Descrivi la campagna in linguaggio naturale. Il chatbot propone i parametri UTM gia pronti e tu puoi modificarli prima di confermare.
          </p>
        </motion.div>

        <motion.div
          initial={{ opacity: 0, y: 20, scale: 0.97 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.45, delay: 0.15 }}
          className="mx-auto max-w-4xl rounded-3xl border border-primary-foreground/10 bg-primary-foreground/[0.04] p-5 shadow-xl shadow-primary/30 backdrop-blur-xl sm:p-6"
        >
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-2">
              <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-accent text-accent-foreground shadow-md shadow-accent/30">
                <Bot className="h-4.5 w-4.5" />
              </div>
              <div>
                <p className="text-sm font-semibold text-primary-foreground">Assistente UTM</p>
                <p className="text-xs text-primary-foreground/55">Guidata, veloce, adatta anche ai non esperti</p>
              </div>
            </div>
            <button
              onClick={openChatbot}
              className="inline-flex items-center gap-2 rounded-xl bg-accent px-4 py-2 text-xs font-semibold text-accent-foreground transition-colors hover:bg-accent/90"
            >
              Apri chatbot
              <ArrowRight className="h-3.5 w-3.5" />
            </button>
          </div>

          <div className="mb-4 rounded-2xl border border-primary-foreground/10 bg-primary-foreground/[0.06] px-4 py-3 text-sm text-primary-foreground/70">
            Es. Campagna Meta per Black Friday, Italia, prospecting, obiettivo traffico al sito
          </div>

          <div className="mb-4 flex flex-wrap gap-2">
            {["Newsletter", "Meta Ads", "Google Ads", "Lancio prodotto"].map((suggestion) => (
              <button
                key={suggestion}
                className="rounded-full border border-primary-foreground/15 bg-primary-foreground/[0.05] px-3 py-1.5 text-xs font-medium text-primary-foreground/80 transition-colors hover:bg-primary-foreground/[0.12]"
              >
                {suggestion}
              </button>
            ))}
          </div>

          <div className="rounded-2xl border border-accent/30 bg-accent/[0.08] p-4">
            <div className="mb-2 flex items-center gap-2 text-accent">
              <MessageCircle className="h-4 w-4" />
              <span className="text-xs font-semibold uppercase tracking-wide">Anteprima UTM</span>
            </div>
            <p className="overflow-x-auto rounded-lg bg-primary/30 px-3 py-2 font-mono text-[11px] text-primary-foreground/85">
              https://example.com/landing?utm_source=meta&utm_medium=paid_social&utm_campaign=bf_2026_prospecting
            </p>
            <div className="mt-3 flex flex-wrap gap-2">
              <span className="rounded-lg bg-primary-foreground/10 px-2.5 py-1 text-[11px] text-primary-foreground/75">utm_source: meta</span>
              <span className="rounded-lg bg-primary-foreground/10 px-2.5 py-1 text-[11px] text-primary-foreground/75">utm_medium: paid_social</span>
              <span className="rounded-lg bg-primary-foreground/10 px-2.5 py-1 text-[11px] text-primary-foreground/75">utm_campaign: bf_2026_prospecting</span>
            </div>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
            <p className="text-xs text-primary-foreground/55">
              Nessun rischio: puoi modificare tutto prima di confermare.
            </p>
            <button
              onClick={onOpenManual}
              className="inline-flex items-center gap-2 rounded-xl border border-primary-foreground/20 px-3.5 py-2 text-xs font-medium text-primary-foreground/80 transition-colors hover:bg-primary-foreground/10"
            >
              Preferisci compilare a mano?
              <Sparkles className="h-3.5 w-3.5" />
            </button>
          </div>
        </motion.div>
      </div>
    </section>
  );
};

export default HeroSection;
