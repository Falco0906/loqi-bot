import "../globals.css";

export const metadata = {
  title: "Loqi — First Meeting",
};

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="auth-dark min-h-screen antialiased">
      <header className="fixed top-0 left-0 w-full z-50 bg-[#141313]/80 backdrop-blur-md px-6 py-6">
        <div className="max-w-[720px] mx-auto flex justify-between items-center">
          <div className="flex items-center space-x-3">
            <div className="flex items-center gap-2">
              <span className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] font-bold text-[#e6e2e1] tracking-tight">
                Loqi
              </span>
              <span className="rounded-full border border-[#4a4549] bg-[#1c1b1b] px-1.5 py-0.5 font-['Geist'] text-[9px] leading-none font-semibold uppercase tracking-[0.12em] text-[#ccc4c9]">
                Beta
              </span>
            </div>
            <span className="h-4 w-px bg-[#4a4549]" />
            <span className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium uppercase tracking-widest text-[#ccc4c9]">
              Welcome
            </span>
          </div>
        </div>
      </header>
      
      <main className="pt-32 pb-16 px-6">
        <div className="max-w-[720px] mx-auto">
          {children}
        </div>
      </main>
    </div>
  );
}
