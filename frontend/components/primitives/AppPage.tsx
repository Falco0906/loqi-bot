"use client";

type Props = {
  children: React.ReactNode;
  className?: string;
};

export default function AppPage({ children, className = "" }: Props) {
  return (
    <div className={`flex h-full flex-col p-6 lg:p-8 animate-fade-in ${className}`}>
      {children}
    </div>
  );
}