"use client";

import { useState, useMemo } from "react";
import { useRouter } from "next/navigation";
import PageHeader from "../../../components/primitives/PageHeader";
import PageSection from "../../../components/primitives/PageSection";
import ProspectCard from "../../../components/prospect/ProspectCard";
import ProspectDrawer from "../../../components/prospect/ProspectDrawer";
import PrimaryButton from "../../../components/shared/PrimaryButton";
import { useProspectRegistry } from "../../../contexts/ProspectRegistryProvider";
import { Prospect } from "../../../lib/types/prospect";

export default function ContactsPage() {
  const router = useRouter();
  const { savedProspects } = useProspectRegistry();
  const [search, setSearch] = useState("");
  const [selectedProspect, setSelectedProspect] = useState<Prospect | null>(null);
  
  const filteredContacts = useMemo(() => {
    return savedProspects.filter(c => 
      c.company.toLowerCase().includes(search.toLowerCase()) ||
      c.contact.toLowerCase().includes(search.toLowerCase()) ||
      c.title.toLowerCase().includes(search.toLowerCase())
    );
  }, [search, savedProspects]);

  return (
    <div className="flex flex-col gap-8 p-8">
      <PageHeader title="Contacts" description="Manage prospects you've saved." />
      
      <div className="flex gap-4 items-center">
        <input 
          className="p-2 border rounded bg-surface w-64"
          placeholder="Search contacts..."
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <select className="p-2 border rounded bg-surface">
          <option>All Filters</option>
          <option>High Confidence</option>
          <option>Needs Follow-up</option>
        </select>
        <PrimaryButton onClick={() => router.push("/discovery")}>Find Prospects</PrimaryButton>
      </div>

      <PageSection>
        {filteredContacts.length > 0 ? (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-4">
            {filteredContacts.map(p => (
              <ProspectCard 
                key={p.id} 
                prospect={p} 
                action="remove"
                onToggle={() => setSelectedProspect(p)} 
              />
            ))}
          </div>
        ) : (
             <div className="flex flex-col items-center justify-center py-20 text-center text-outline">
                <p className="text-body-lg">You haven't saved any prospects yet.</p>
                <PrimaryButton className="mt-4" onClick={() => router.push("/discovery")}>Find Prospects</PrimaryButton>
             </div>
        )}
      </PageSection>

      <ProspectDrawer 
        isOpen={!!selectedProspect}
        prospect={selectedProspect}
        onClose={() => setSelectedProspect(null)}
      />
    </div>
  );
}
