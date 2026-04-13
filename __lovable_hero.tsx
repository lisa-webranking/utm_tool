import { motion } from "framer-motion";
import { Database, Bot, GitCompareArrows, ShieldCheck, MessageCircle, ArrowRight, Sparkles } from "lucide-react";
import { Button } from "@/components/ui/button";

const features = [
  {
    icon: Database,
    title: "Dati reali da GA4",
    description: "Source e medium precaricati dalla tua property: niente più errori di digitazione.",
  },
  {
    icon: Bot,
    title: "Assistente AI dedicato",
    description: "Un chatbot che ti guida nella scelta dei parametri, suggerendo best practice.",
  },
  {
    icon: GitCompareArrows,
    title: "Naming convention unificata",
    description: "Parametri coerenti tra team e campagne, addio a UTM duplicati o incoerenti.",
  },
  {
    icon: ShieldCheck,
    title: "Validazione automatica",
    description: "Controllo in tempo reale di errori, duplicati e formattazione prima di generare l'URL.",
  },
];

const openChatbot = () => {
  // Try common chatbot widget triggers
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
  // Fallback: trigger custom event
  window.dispatchEvent(new CustomEvent('open-chatbot'));
  // Fallback: try Tidio / Crisp / Intercom APIs
  if ((window as any).tidioChatApi) (window as any).tidioChatApi.open();
  else if ((window as any).$crisp) (window as any).$crisp.push(["do", "chat:open"]);
  else if ((window as any).Intercom) (window as any).Intercom('show');
};

const HeroSection = () => {
  return (
    <section className="relative overflow-hidden bg-primary">
      {/* Gradient orbs */}
      <div className="pointer-events-none absolute inset-0">
        <div className="absolute -left-20 -top-20 h-[400px] w-[400px] rounded-full bg-accent/8 blur-[120px]" />
        <div className="absolute -bottom-20 -right-20 h-[300px] w-[300px] rounded-full bg-accent/10 blur-[100px]" />
        <div className="absolute left-1/2 top-1/2 h-[200px] w-[200px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-accent/5 blur-[80px]" />
      </div>

      {/* Grid pattern overlay */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.03]"
        style={{
          backgroundImage: `linear-gradient(hsl(var(--primary-foreground)) 1px, transparent 1px), linear-gradient(90deg, hsl(var(--primary-foreground)) 1px, transparent 1px)`,
          backgroundSize: "60px 60px",
        }}
      />

      <div className="container relative z-10 mx-auto max-w-6xl px-6 pb-14 pt-16">
        <motion.div
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ duration: 0.6 }}
          className="text-center"
        >
          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.4, delay: 0.1 }}
            className="mb-5 inline-flex items-center gap-2 rounded-full border border-accent/20 bg-accent/10 px-4 py-1.5"
          >
            <span className="h-1.5 w-1.5 rounded-full bg-accent animate-pulse" />
            <span className="text-xs font-medium text-accent">Connesso a GA4 in tempo reale</span>
          </motion.div>

          <h1 className="mb-4 font-heading text-3xl font-bold tracking-tight text-primary-foreground sm:text-4xl md:text-5xl">
            Smart UTM
            <span className="relative ml-3 text-accent">
              Assistant
              <svg className="absolute -bottom-1 left-0 w-full" viewBox="0 0 200 8" fill="none">
                <path d="M1 5.5C40 2 80 2 100 3.5C120 5 160 5 199 2.5" stroke="hsl(var(--accent))" strokeWidth="2" strokeLinecap="round" opacity="0.5" />
              </svg>
            </span>
          </h1>
          <p className="mx-auto mb-8 max-w-xl text-sm leading-relaxed text-primary-foreground/60 sm:text-base">
            Crea e valida link UTM con guida passo-passo, leggendo in tempo reale
            source e medium dalla tua property GA4.
          </p>
        </motion.div>

        {/* CTA Chatbot - Primary action */}
        <motion.div
          initial={{ opacity: 0, y: 20, scale: 0.95 }}
          animate={{ opacity: 1, y: 0, scale: 1 }}
          transition={{ duration: 0.5, delay: 0.3 }}
          className="mx-auto mb-12 max-w-lg"
        >
          <button
            onClick={openChatbot}
            className="group relative w-full overflow-hidden rounded-2xl border border-accent/30 bg-accent/10 p-1 shadow-lg shadow-accent/10 backdrop-blur-sm transition-all duration-300 hover:border-accent/50 hover:shadow-xl hover:shadow-accent/20"
          >
            <div className="relative flex items-center gap-4 rounded-xl bg-primary-foreground/[0.06] px-6 py-5 transition-all duration-300 group-hover:bg-primary-foreground/[0.1]">
              {/* Animated icon */}
              <div className="relative flex h-14 w-14 shrink-0 items-center justify-center rounded-2xl bg-accent shadow-lg shadow-accent/30">
                <MessageCircle className="h-6 w-6 text-accent-foreground" />
                <motion.div
                  className="absolute -right-1 -top-1 flex h-5 w-5 items-center justify-center rounded-full bg-primary-foreground"
                  animate={{ scale: [1, 1.2, 1] }}
                  transition={{ repeat: Infinity, duration: 2, ease: "easeInOut" }}
                >
                  <Sparkles className="h-3 w-3 text-primary" />
                </motion.div>
              </div>

              <div className="flex-1 text-left">
                <span className="mb-0.5 block font-heading text-base font-bold text-primary-foreground sm:text-lg">
                  Crea UTM con l'Assistente AI
                </span>
                <span className="block text-xs text-primary-foreground/50 sm:text-sm">
                  Apri il chatbot e lasciati guidare passo dopo passo
                </span>
              </div>

              <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-accent/20 transition-all duration-300 group-hover:bg-accent/30">
                <ArrowRight className="h-5 w-5 text-accent transition-transform duration-300 group-hover:translate-x-0.5" />
              </div>
            </div>
          </button>

          <p className="mt-3 text-center text-[11px] text-primary-foreground/35">
            Oppure compila manualmente i campi qui sotto ?
          </p>
        </motion.div>

        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {features.map((feature, index) => (
            <motion.div
              key={feature.title}
              initial={{ opacity: 0, y: 16 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.4, delay: 0.5 + index * 0.08 }}
              className="group relative rounded-2xl border border-primary-foreground/[0.06] bg-primary-foreground/[0.03] p-5 backdrop-blur-sm transition-all duration-300 hover:border-accent/20 hover:bg-primary-foreground/[0.07]"
            >
              <div className="mb-3 inline-flex rounded-xl bg-accent/15 p-2.5">
                <feature.icon className="h-4.5 w-4.5 text-accent" strokeWidth={2} />
              </div>
              <h3 className="mb-1 font-heading text-sm font-semibold text-primary-foreground">
                {feature.title}
              </h3>
              <p className="text-xs leading-relaxed text-primary-foreground/45">
                {feature.description}
              </p>
            </motion.div>
          ))}
        </div>
      </div>
    </section>
  );
};

export default HeroSection;
