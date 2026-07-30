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
    <div className="min-h-screen bg-[#fdf8f8] antialiased">
      <header className="fixed top-0 left-0 w-full z-50 bg-[#fdf8f8]/80 backdrop-blur-md px-6 py-6">
        <div className="max-w-[720px] mx-auto flex justify-between items-center">
          <div className="flex items-center space-x-3">
            <span className="font-['Libre_Caslon_Text'] text-[24px] leading-[1.4] font-bold text-[#000000] tracking-tight">
              Loqi
            </span>
            <span className="h-4 w-px bg-[#c4c7c7]/40" />
            <span className="font-['Geist'] text-[13px] leading-[1.2] tracking-[0.02em] font-medium uppercase tracking-widest text-[#444748]">
              Continuous Strategy
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