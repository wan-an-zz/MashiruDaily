using System;

namespace MashiruDaily.Core.Events;

public class GetMessageSuccessfulEventArgs : EventArgs
{
    public string Message { get; set; }

    public GetMessageSuccessfulEventArgs(string message)
    {
        Message = message;
    }
}