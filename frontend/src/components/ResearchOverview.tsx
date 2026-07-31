export default function ResearchOverview() {
  return (
    <section className="bg-surface rounded-lg shadow-card p-6">
      <h2 className="text-xl font-bold text-gray-900 mb-4">
        Research Status
      </h2>
      <div className="space-y-4 text-sm leading-6 text-gray-700">
        <p>
          <strong>Catalogue metadata:</strong> seven public portal catalogues
          are available through the local read-only catalogue CLI; the product
          observatory is not connected yet.
        </p>
        <p>
          <strong>Analytical data:</strong> no verified canonical flexibility
          signal or zone dataset is available in this release.
        </p>
      </div>
    </section>
  );
}
