using System.Threading.Tasks;
using MashiruDaily.Core.Models;

namespace MashiruDaily.Core.Abstracts;

/// <summary>
/// Persistence abstraction for Hermes AI-sync settings. Swap the implementation
/// for a different store without touching the rest of the app.
/// </summary>
public interface IHermesSettingsRepository
{
    Task<HermesSettings> LoadAsync();

    Task SaveAsync(HermesSettings settings);
}
