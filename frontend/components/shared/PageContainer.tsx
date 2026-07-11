type Props = {
  children: React.ReactNode;
  className?: string;
};

export default function PageContainer({ children, className = "" }: Props) {
  return (
    <div className={`mx-auto w-full max-w-[1400px] px-6 py-6 sm:px-8 ${className}`}>
      {children}
    </div>
  );
}
