import { Prospect } from "../../lib/types/prospect";
import PageHeader from "../primitives/PageHeader";
import PageSection from "../primitives/PageSection";
import PrimaryButton from "../shared/PrimaryButton";

interface Props {
  prospect: Prospect;
  onClose: () => void;
}

export default function ProspectDetails({ prospect, onClose }: Props) {
  return (
    <>
      <PageHeader 
        title={prospect.contact} 
        description={prospect.title}
        actions={<PrimaryButton onClick={onClose}>Close</PrimaryButton>}
      />
      <div className="p-6">
        <PageSection title="Company" description={prospect.company}>
          <p className="text-body-sm text-outline">{prospect.summary}</p>
        </PageSection>
      </div>
    </>
  );
}
