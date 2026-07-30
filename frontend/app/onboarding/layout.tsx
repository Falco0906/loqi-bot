"use client";

export default function OnboardingLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen onb-surface antialiased">
      {children}
    </div>
  );
}
