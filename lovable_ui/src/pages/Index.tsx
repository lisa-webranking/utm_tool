import { useRef, useState } from "react";
import { ChevronDown } from "lucide-react";
import HeroSection from "@/components/HeroSection";
import UTMBuilder from "@/components/UTMBuilder";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";

const Index = () => {
  const [manualOpen, setManualOpen] = useState(false);
  const manualSectionRef = useRef<HTMLElement | null>(null);

  const openManualSection = () => {
    setManualOpen(true);
    setTimeout(() => {
      manualSectionRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
    }, 100);
  };

  return (
    <div className="min-h-screen bg-background">
      <header className="sticky top-0 z-50 border-b bg-card/80 backdrop-blur-xl">
        <div className="container mx-auto flex max-w-6xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-3">
            <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-gradient-to-br from-accent to-accent/70 font-heading text-sm font-bold text-accent-foreground shadow-md">
              W
            </div>
            <div>
              <span className="font-heading text-sm font-bold tracking-wide text-foreground">SMART UTM</span>
              <span className="ml-2 hidden rounded-full bg-accent/15 px-2 py-0.5 text-[10px] font-semibold text-accent sm:inline-block">
                BETA
              </span>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <button className="rounded-lg px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:text-foreground">
              Come funziona
            </button>
            <button className="rounded-xl border bg-card px-4 py-1.5 text-sm font-medium text-foreground shadow-sm transition-all hover:bg-muted hover:shadow-md">
              Esempi
            </button>
          </div>
        </div>
      </header>

      <HeroSection onOpenManual={openManualSection} />

      <section ref={manualSectionRef} className="container mx-auto max-w-6xl px-6 pb-16 pt-10">
        <Collapsible
          open={manualOpen}
          onOpenChange={setManualOpen}
          className="rounded-2xl border bg-card shadow-sm"
        >
          <CollapsibleTrigger
            className="flex w-full items-center justify-between px-5 py-4 text-left"
            aria-label="Preferisci compilare manualmente? Apri il builder avanzato"
          >
            <div>
              <span className="mb-1 inline-flex rounded-full border border-accent/30 bg-accent/10 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-accent">
                Modalita esperto
              </span>
              <p className="text-sm font-semibold text-foreground">
                Preferisci compilare manualmente? Apri il builder avanzato
              </p>
              <p className="text-xs text-muted-foreground">
                Usalo solo se vuoi controllare ogni singolo parametro manualmente.
              </p>
            </div>
            <ChevronDown
              className={`h-4 w-4 text-muted-foreground transition-transform ${manualOpen ? "rotate-180" : ""}`}
            />
          </CollapsibleTrigger>

          <CollapsibleContent id="manual-builder" className="border-t">
            <UTMBuilder embedded />
          </CollapsibleContent>
        </Collapsible>
      </section>

      <footer className="border-t bg-card">
        <div className="container mx-auto flex max-w-6xl flex-col items-center justify-between gap-3 px-6 py-8 sm:flex-row">
          <div className="flex items-center gap-2">
            <div className="flex h-6 w-6 items-center justify-center rounded-md bg-accent/20 font-heading text-[10px] font-bold text-accent">
              W
            </div>
            <span className="text-xs font-medium text-muted-foreground">Smart UTM Assistant</span>
          </div>
          <p className="text-xs text-muted-foreground/60">
            © {new Date().getFullYear()} Powered by Webranking — All rights reserved
          </p>
        </div>
      </footer>
    </div>
  );
};

export default Index;
